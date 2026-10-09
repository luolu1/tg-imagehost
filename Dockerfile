FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first so the layer is cached across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code.
COPY . .

# SQLite database + image cache live here. Mount a volume to persist.
RUN mkdir -p /app/data/cache

EXPOSE 8080

# Default runs the web process; the bot service overrides this command.
CMD ["python", "run_web.py"]
