# 一个动态域名客户端

  - 用python写的一个针对CloudFlare动态域名客户端
  - 当你需要访问的IP地址总是变化的时候，你就需要一个动态域名客户端去更新你的域名对应的IP了，这个客户端很好的解决了这个问题。

## Features:
* Dockerfile的安装方式，简单快捷。
* 使用json的配置文件

## json的配置文件如下
  ```json
  {
    "domains": [{
      "hosts": [{
        "name": "host name"
      }],
      "name": "domain name"
    }],
    "user": {
      "api_key": "your cloudflare api_key",
      "email": "your cloudflare email"
    },
    "interval": 10
  }
  ```

## 安装:
  ```bash
  docker build -t ddns .
  ```

## 启动
  - 映射卷时本地目录必须是绝对路径

  ```bash
  docker run --restart=always -d -v /root/ddns/conf:/usr/local/ddns/conf --name=ddns ddns:v1.0
  ```

