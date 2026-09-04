FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RUNTIME_DIRECTORY=/app/runtime \
    DATABASE_PATH=/app/runtime/identity_verification.db \
    EASYOCR_MODEL_DIRECTORY=/app/runtime/easyocr_models

RUN apt-get update \
    && apt-get install --no-install-recommends -y curl libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY ai ./ai
COPY backend ./backend
COPY web ./web
COPY certs ./certs
COPY models ./models
RUN useradd --create-home --uid 10001 drishti \
    && mkdir -p /app/runtime \
    && chown -R drishti:drishti /app/runtime

USER drishti
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl --fail http://127.0.0.1:8000/health || exit 1

# One worker is intentional: active liveness sessions are held in memory.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips=*"]
