web: gunicorn --config gunicorn.conf.py pypistats.run:app
worker: celery -A pypistats.extensions.celery worker -l info --concurrency=1
beat: celery -A pypistats.extensions.celery beat -l info
flower: flower -A pypistats.extensions.celery -l info --port=$PORT
release: flask db upgrade