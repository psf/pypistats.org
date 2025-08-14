web: gunicorn --config gunicorn.conf.py pypistats.run:app
worker: celery -A pypistats.extensions.celery worker -l info --concurrency=1
worker-beat: celery -A pypistats.extensions.celery beat -l info --scheduler redbeat.RedBeatScheduler
release: flask db upgrade