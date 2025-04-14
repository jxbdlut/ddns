FROM python:3.10-alpine
# 替换为国内镜像源
RUN sed -i 's/dl-cdn.alpinelinux.org/mirrors.aliyun.com/g' /etc/apk/repositories

# 更新包索引并安装 tzdata
RUN apk update && apk add --no-cache tzdata

# 设置时区（例如 Asia/Shanghai）
ENV TZ=Asia/Shanghai
RUN ln -sf /usr/share/zoneinfo/$TZ /etc/localtime && echo "$TZ" > /etc/timezone
ENV PYTHON_ENVIRONMENT="" PYTHONUNBUFFERED=1

ADD . /usr/local/ddns
WORKDIR /usr/local/ddns
RUN pip install -r requirements.txt

ENTRYPOINT python app.py
