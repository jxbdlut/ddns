FROM python:3.7.3-alpine
ENV PYTHON_ENVIRONMENT="" PYTHONUNBUFFERED=1
ADD . /usr/local/ddns
WORKDIR /usr/local/ddns
RUN pip install -r requirements.txt

ENTRYPOINT python app.py
