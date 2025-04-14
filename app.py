from urllib.request import urlopen
from urllib.request import Request
from urllib.error import URLError
from urllib.error import HTTPError
from tornado import ioloop
import datetime
import functools
import json
import sys
import os
import logging

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

    def restart(self):
        self.timer.callback_time = self.interval * 1000
        self.timer.start()

    def timer_func(self):
        logging.info("interval:{} now:{}".format(self.interval, datetime.datetime.now()))

    def get_config(self, config_path):
        env = os.environ.get('PYTHON_ENVIRONMENT') if os.environ.get('PYTHON_ENVIRONMENT') else ""
        config_file_name = config_path + "/conf/conf" + env + ".json"
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
            self.public_ipv4 = urlopen(Request("https://www.jxbdlut.xyz/cgi-bin/get_my_ip", headers=header), timeout=10).read().rstrip().decode("utf-8")
            # logging.info("ipv4:{}".format(self.public_ipv4))
        except URLError as e:
            if isinstance(e.reason, TimeoutError):
                logging.error("* no public IPv4 address detected server timeout")
            else:
                logging.error(f"* no public IPv4 address detected reaon {e.reason}")
        except Exception as e:
            logging.error(f"* no public IPv4 address detected reaon {e}")
        try:
            header = {'User-Agent': 'Mozilla/5.0 openwrt-koolshare-mod-v2.31'}
            self.public_ipv6 = urlopen(Request("https://ipv6.jxbdlut.xyz/cgi-bin/get_my_ip", headers=header),  timeout=10).read().rstrip().decode("utf-8")
            # logging.info("ipv6:{}".format(self.public_ipv6))
        except URLError as e:
            if isinstance(e.reason, TimeoutError):
                logging.error("* no public IPv6 address detected server timeout")
            else:
                logging.error(f"* no public IPv6 address detected reaon {e.reason}")
        except Exception as e:
            logging.error(f"* no public IPv6 address detected reaon {e}")

    def update_zone_id(self, domain):
        if "id" in domain:
            return
        try:
            logging.info("* zone id for {} is missing. attempting to get it from cloudflare...".format(domain["name"]))
            req = Request(self.base_url, headers=self.content_header)
            for ret_domain in json.loads(urlopen(req).read().decode("utf-8"))["result"]:
                if domain["name"] == ret_domain["name"]:
                    logging.info("* zone id for {} is {}".format(domain["name"], ret_domain["id"]))
                    domain["id"] = ret_domain["id"] if ret_domain["id"] is not None else domain["id"]
        except HTTPError:
            logging.error("* could not get zone id for: {0}".format(domain))
            logging.error("* possible causes: wrong domain and/or auth credentials")

    def update_host_id(self, domain, host):
        if "A_id" in host or "AAAA_id" in host:
            return
        full_domain = host["name"] + "." + domain["name"]
        logging.info("* host id for {} is missing. attempting to get it from cloudflare...".format(full_domain))
        req = Request(self.base_url + domain["id"] + "/dns_records/", headers=self.content_header)
        result = json.loads(urlopen(req).read().decode("utf-8"))["result"]
        # logging.info(result)
        for e in result:
            if full_domain == e["name"]:
                logging.info("* host id for {} type {} is {}".format(full_domain, e["type"], e["id"]))
                host[e["type"] + "_id"] = e["id"] if e["id"] is not None else host[e["type"] + "_id"]
        

    def get_need_update_hosts(self, domain, host):
        host["A"] = None if "A" not in host else host["A"]
        host["AAAA"] = None if "AAAA" not in host else host["AAAA"]
        if self.public_ipv4 != host["A"] and self.public_ipv4 is not None:
            logging.info("new ipv4:{} old ipv4:{}".format(self.public_ipv4, host["A"]))
            self.need_update_hosts.append({
                "ip": self.public_ipv4,
                "type": "A",
                "host": host,
                "domain": domain,
                'ttl': 60
            })
        if "AAAA" not in host or self.public_ipv6 != host["AAAA"] and self.public_ipv6 is not None:
            logging.info("new ipv6:{} old ipv6:{}".format(self.public_ipv6, host["AAAA"]))
            self.need_update_hosts.append({
                "ip": self.public_ipv6,
                "type": "AAAA",
                "host": host,
                "domain": domain,
                'ttl': 60
            })

    def update_host_on_cloudflare(self):
        for e in self.need_update_hosts:
            data = json.dumps({
                "id": e["host"][e["type"] + "_id"],
                "type": e["type"],
                "name": e["host"]["name"],
                "content": e["ip"],
                "ttl": e["ttl"]
            })
            uri = "{0}{1}{2}{3}".format(self.base_url, e["domain"]["id"], "/dns_records/", e["host"][e["type"] + "_id"])
            req = Request(uri, data=data.encode("utf-8"), headers=self.content_header)
            req.method = "PUT"
            rsp = json.loads(urlopen(req).read().decode("utf-8"))
            if rsp["success"]:
                e["host"][e["type"]] = e["ip"]
                full_domain = e["host"]["name"] + "." + e["domain"]["name"]
                logging.info("* update successful (type: {0}, ip: {1}, ip: {2})".format(e["type"], full_domain, e["ip"]))

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
