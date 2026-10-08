FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    SMARTPOST_DATA_DIR=/tmp/smartpost-data \
    SMARTPOST_WEB_HOST=0.0.0.0

WORKDIR /app
COPY requirements-web.txt /app/requirements-web.txt
RUN pip install --no-cache-dir -r /app/requirements-web.txt \
    && python -m playwright install --with-deps chromium

COPY . /app
RUN mkdir -p /tmp/smartpost-data

CMD ["python", "web_server.py"]
