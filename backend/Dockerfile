FROM python:3.12-slim

# 3.12 rather than 3.14: every dependency has a prebuilt wheel there, so the
# image builds without a compiler toolchain. The app itself runs on 3.11+.

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY config/ ./config/
COPY data/ ./data/

EXPOSE 8000

# A healthcheck so compose can hold the front end back until the API answers.
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"

CMD ["uvicorn", "email_assistant.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
