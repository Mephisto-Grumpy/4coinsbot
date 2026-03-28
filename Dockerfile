FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HEARTBEAT_FILE=/tmp/4coinsbot.heartbeat \
    HEARTBEAT_MAX_AGE_SEC=120

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD python /app/healthcheck.py

CMD ["python", "/app/src/main.py"]
