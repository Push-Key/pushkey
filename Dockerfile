FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    fastapi "uvicorn[standard]" "passlib[bcrypt]" "python-jose[cryptography]"

COPY pushkey_cloud_api.py ./

ENV PUSHKEY_DATA_DIR=/data
VOLUME /data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health', timeout=3)" || exit 1

CMD ["uvicorn", "pushkey_cloud_api:app", "--host", "0.0.0.0", "--port", "8000"]
