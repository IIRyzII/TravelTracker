# ORBIT production image — runs anywhere that runs containers (Render, Fly, Railway…)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ORBIT_ENV=production \
    DATABASE_PATH=/data/traveltracker.db \
    PORT=8000

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
# gzip + brotli copies of the static files, which WhiteNoise serves automatically
RUN python -m whitenoise.compress static \
    && useradd --system --home /app orbit \
    && mkdir -p /data

EXPOSE 8000
# starts as root only to hand the mounted data volume to the app user
CMD ["sh", "scripts/docker-start.sh"]
