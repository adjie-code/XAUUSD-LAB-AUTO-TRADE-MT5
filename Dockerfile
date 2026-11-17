FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DASHBOARD_PORT=8090

WORKDIR /app

COPY . /app

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/broker', timeout=3)" || exit 1

# DB kosong dibuat otomatis; data candle/DB tetap di volume ./data.
CMD ["sh", "-c", "python3 db_init.py && exec python3 app.py"]
