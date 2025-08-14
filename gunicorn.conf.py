import os

# Server socket
bind = f"0.0.0.0:{os.environ.get('PORT', 5000)}"

# Worker processes
workers = int(os.environ.get("WEB_CONCURRENCY", 2))
worker_class = "sync"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50
preload_app = True

# Timeout
timeout = 30
graceful_timeout = 30
keepalive = 2

# Logging
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")
access_log_format = '%({x-forwarded-for}i)s %(l)s %(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# Process naming
proc_name = "pypistats"

# Server mechanics
daemon = False
pidfile = None
user = None
group = None
tmp_upload_dir = None
