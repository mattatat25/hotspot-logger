FROM python:3.12-alpine
WORKDIR /app
COPY app.py maintenance.py /app/
COPY assets/ /app/assets/
RUN apk add --no-cache tzdata && addgroup -g 10001 -S app && adduser -u 10001 -S -G app app && mkdir /data && chown app:app /data
USER app
ENV DB_PATH=/data/logger.sqlite PORT=8787
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8787')+'/healthz',timeout=3)"]
CMD ["python", "-u", "app.py"]
