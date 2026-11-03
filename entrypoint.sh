#!/bin/sh
set -e

# One worker: the updater thread lives in the web process
exec gunicorn --workers 1 --threads 8 --bind "0.0.0.0:${PORT:-5000}" --access-logfile - app.webapp:app
