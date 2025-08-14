#!/usr/bin/env bash

if [[ "$1" = "webdev" ]]
then
  exec flask run --host 0.0.0.0
fi

if [[ "$1" = "web" ]]
then
  exec gunicorn --config gunicorn.conf.py pypistats.run:app
fi

if [[ "$1" = "celery" ]]
then
  exec celery -A pypistats.extensions.celery worker -l info --concurrency=1
fi

if [[ "$1" = "beat" ]]
then
  exec celery -A pypistats.extensions.celery beat -l info --scheduler redbeat.RedBeatScheduler
fi

if [[ "$1" = "flower" ]]
then
  exec flower -A pypistats.extensions.celery -l info
fi

if [[ "$1" = "migrate" ]]
then
  exec flask db upgrade
fi

if [[ "$1" = "seeds" ]]
then
  exec python -m migrations.seeds
fi

# Default: run the command as-is
exec "$@"