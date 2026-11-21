FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-api.txt ./
RUN pip install --no-cache-dir -r requirements-api.txt

COPY pushkey_cloud_api.py ./
COPY pushkey_shared.py ./

ENV PUSHKEY_DATA_DIR=/data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health', timeout=3)" || exit 1

CMD ["uvicorn", "pushkey_cloud_api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-proxy-headers"]
