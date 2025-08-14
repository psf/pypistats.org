import os

# Server socket
# Check if we should bind to Unix socket (for Cabotage) or TCP port
if os.environ.get("BIND_UNIX_SOCKET"):
    bind = "unix:/var/run/cabotage/cabotage.sock"
    # Ensure proper permissions for the socket
    umask = 0o117  # Results in socket permissions of 660
else:
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
