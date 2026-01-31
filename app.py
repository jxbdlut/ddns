from tornado import ioloop
import datetime
import functools
import json
import sys
import os
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 配置日志格式，包含时间戳
logging.basicConfig(
    level=logging.INFO,  # 设置日志级别
    format='%(asctime)s %(message)s',  # 日志格式
    datefmt='%Y-%m-%d %H:%M:%S',  # 时间戳格式
    handlers=[logging.StreamHandler()]  # 输出到控制台
)

def get_current_path():
    paths = sys.path
    current_file = os.path.basename(__file__)
    for path in paths:
        if current_file in os.listdir(path):
            return path

class CloudFlareDDns:

    def __new__(cls, *args, **kwargs):
        return object.__new__(cls)

    def __init__(self, config_path=None):
        self.base_url = "https://api.cloudflare.com/client/v4/zones/"
        self.config = None
        self.public_ipv4 = None
        self.public_ipv6 = None
        self.need_update_hosts = []
        self.get_config(config_path)
        self.interval = self.config["interval"]
        self.timer = ioloop.PeriodicCallback(self.update_cloudflare, self.interval * 1000)
        self.content_header = {
            "X-Auth-Email": self.config["user"]["email"],
            "X-Auth-Key": self.config["user"]["api_key"],
            "Content-type": "application/json",
            "user-agent": "Mozilla/5.0 "
        }
        
        # 配置 requests session 和重试策略
        self.session = requests.Session()
        
        # Cloudflare API 重试策略（更激进）
        cf_retry = Retry(
            total=5,
            connect=5,
            read=5,
            redirect=5,
            backoff_factor=1.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "PUT", "POST"]
        )
        
        # IP 获取服务重试策略（处理连接断开）
        ip_retry = Retry(
            total=5,
            connect=5,
            read=5,
            redirect=5,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"],
            raise_on_redirect=False,
            raise_on_status=False
        )
        
        # 为 Cloudflare 配置适配器
        cf_adapter = HTTPAdapter(max_retries=cf_retry, pool_connections=10, pool_maxsize=10)
        self.session.mount("https://api.cloudflare.com", cf_adapter)
        
        # 为 IP 服务配置单独的 session
        self.ip_session = requests.Session()
        ip_adapter = HTTPAdapter(max_retries=ip_retry, pool_connections=5, pool_maxsize=5)
        self.ip_session.mount("http://", ip_adapter)
        self.ip_session.mount("https://", ip_adapter)

    def restart(self):
        self.update_cloudflare()
        self.timer.callback_time = self.interval * 1000
        self.timer.start()

    def timer_func(self):
        logging.info(f"interval:{self.interval} now:{datetime.datetime.now()}")

    def get_config(self, config_path):
        env = os.environ.get('PYTHON_ENVIRONMENT') if os.environ.get('PYTHON_ENVIRONMENT') else ""
        config_file_name = config_path + "/conf/conf." + env + ".json"
        with open(config_file_name, "r") as file:
            try:
                self.config = json.loads(file.read())
                if not self.config["user"]["email"] or not self.config["user"]["api_key"]:
                    logging.error("* missing CloudFlare auth credentials")
                    exit(0)
                return
            except ValueError:
                logging.error("the config file is wrong")
                exit(0)

    def update_my_ip(self):
        try:
            header = {'User-Agent': 'Mozilla/5.0 openwrt-koolshare-mod-v2.31'}
            response = self.ip_session.get("https://ipv4.jxbdlut.xyz/cgi-bin/get_my_ip", headers=header, timeout=(15, 45))
            response.raise_for_status()
            self.public_ipv4 = response.text.rstrip()
            logging.info(f"IPv4 updated: {self.public_ipv4}")
        except requests.exceptions.ConnectionError as e:
            logging.error(f"* no public IPv4 address detected connection error: {type(e).__name__}")
        except requests.Timeout:
            logging.error("* no public IPv4 address detected server timeout")
        except Exception as e:
            logging.error(f"* no public IPv4 address detected: {e}")
        
        try:
            header = {'User-Agent': 'Mozilla/5.0 openwrt-koolshare-mod-v2.31'}
            response = self.ip_session.get("https://ipv6.jxbdlut.xyz/cgi-bin/get_my_ip", headers=header, timeout=(15, 45))
            response.raise_for_status()
            self.public_ipv6 = response.text.rstrip()
            logging.info(f"IPv6 updated: {self.public_ipv6}")
        except requests.exceptions.ConnectionError as e:
            logging.error(f"* no public IPv6 address detected connection error: {type(e).__name__}")
        except requests.Timeout:
            logging.error("* no public IPv6 address detected server timeout")
        except Exception as e:
            logging.error(f"* no public IPv6 address detected: {e}")

    def update_zone_id(self, domain):
        if "id" in domain:
            return
        try:
            logging.info(f"* zone id for {domain['name']} is missing. attempting to get it from cloudflare...")
            response = self.session.get(self.base_url, headers=self.content_header, timeout=(30, 60))
            response.raise_for_status()
            for ret_domain in response.json()["result"]:
                if domain["name"] == ret_domain["name"]:
                    logging.info(f"* zone id for {domain['name']} is {ret_domain['id']}")
                    domain["id"] = ret_domain["id"] if ret_domain["id"] is not None else domain["id"]
        except requests.exceptions.HTTPError as e:
            logging.error(f"* could not get zone id for: {domain} {e}")
        except Exception as e:
            logging.error(f"* could not get zone id for: {domain} {e}")

    def update_host_id(self, domain, host):
        if "A_id" in host and "AAAA_id" in host:
            return
        full_domain = host["name"] + "." + domain["name"]
        logging.info(f"* host id for {full_domain} is missing. attempting to get it from cloudflare...")
        url = self.base_url + domain["id"] + "/dns_records/"
        try:
            response = self.session.get(url, headers=self.content_header, timeout=(30, 60))
            response.raise_for_status()
            result = response.json()["result"]
            # logging.info(result)
            for e in result:
                if full_domain == e["name"]:
                    logging.info(f"* host id for {full_domain} type {e['type']} is {e['id']}")
                    host[e["type"] + "_id"] = e["id"] if e["id"] is not None else host[e["type"] + "_id"]
        except requests.exceptions.HTTPError as e:
            logging.error(f"* could not get host id for: {domain} {e.response.reason}")
        except Exception as e:
            logging.error(f"* could not get host id for: {domain} {e}")
        

    def get_need_update_hosts(self, domain, host):
        host["A"] = None if "A" not in host else host["A"]
        host["AAAA"] = None if "AAAA" not in host else host["AAAA"]
        if self.public_ipv4 != host["A"] and self.public_ipv4 is not None:
            logging.info(f"new ipv4:{self.public_ipv4} old ipv4:{host['A']}")
            self.need_update_hosts.append({
                "ip": self.public_ipv4,
                "type": "A",
                "host": host,
                "domain": domain,
                'ttl': 60
            })
        if "AAAA" not in host or self.public_ipv6 != host["AAAA"] and self.public_ipv6 is not None:
            logging.info(f"new ipv6:{self.public_ipv6} old ipv6:{host['AAAA']}")
            self.need_update_hosts.append({
                "ip": self.public_ipv6,
                "type": "AAAA",
                "host": host,
                "domain": domain,
                'ttl': 60
            })

    def update_host_on_cloudflare(self):
        for enum in self.need_update_hosts:
            data = json.dumps({
                "id": enum["host"][enum["type"] + "_id"],
                "type": enum["type"],
                "name": enum["host"]["name"],
                "content": enum["ip"],
                "ttl": enum["ttl"]
            })
            if enum["type"] + "_id" not in enum["host"]:
                continue
            uri = f"{self.base_url}{enum['domain']['id']}/dns_records/{enum['host'][enum['type'] + '_id']}"
            # uri = "{0}{1}{2}{3}".format(self.base_url, enum["domain"]["id"], "/dns_records/", enum["host"][enum["type"] + "_id"])
            # logging.info(uri)
            full_domain = enum["host"]["name"] + "." + enum["domain"]["name"]
            try:
                response = self.session.put(uri, data=data, headers=self.content_header, timeout=(30, 60))
                response.raise_for_status()
                rsp = response.json()
                if rsp["success"]:
                    enum["host"][enum["type"]] = enum["ip"]
                    full_domain = enum["host"]["name"] + "." + enum["domain"]["name"]
                    logging.info(f"* update successful (type: {enum['type']}, domain: {full_domain}, ip: {enum['ip']})")
            except requests.Timeout:
                logging.error(f"* update (type: {enum['type']}, domain: {full_domain}, ip: {enum['ip']}) failed server timeout")
            except requests.exceptions.HTTPError as e:
                logging.error(f"* update (type: {enum['type']}, domain: {full_domain}, ip: {enum['ip']}) failed {e}")
            except Exception as e:
                logging.error(f"* update (type: {enum['type']}, domain: {full_domain}, ip: {enum['ip']}) failed {e}")

    def update_cloudflare(self):
        self.need_update_hosts = []
        self.update_my_ip()
        for domain in self.config["domains"]:
            if not domain["name"]:
                logging.error("* missing domain name")
                continue

            self.update_zone_id(domain)

            for host in domain["hosts"]:
                if not host["name"]:
                    logging.error("* host name missing")
                    continue

                self.update_host_id(domain, host)
                self.get_need_update_hosts(domain, host)
                self.update_host_on_cloudflare()


def main():
    CloudFlareDDns(get_current_path()).restart()
    ioloop.IOLoop.instance().start()

 
if __name__ == "__main__":
    main()
