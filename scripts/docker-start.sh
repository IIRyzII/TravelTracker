#!/bin/sh
# Container entry point: give the (root-owned) data volume to the app user,
# then run gunicorn as that user. One worker process keeps the in-memory rate
# limits and caches shared; threads handle concurrent requests.
set -e
chown -R orbit /data
exec setpriv --reuid=orbit --regid=orbit --init-groups \
  gunicorn wsgi:app --workers 1 --threads 8 --bind "0.0.0.0:${PORT:-8000}" \
  --access-logfile - --timeout 60
