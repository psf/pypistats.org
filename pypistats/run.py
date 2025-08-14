"""Run the application."""

import os

from flask import g
from flask import redirect
from flask import request
from flask import session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

from pypistats.application import create_app
from pypistats.config import configs
from pypistats.models.user import User

# change this for migrations
env = os.environ.get("ENV", "development")

app = create_app(configs[env])

# Rate limiting per IP/worker
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=2)
limiter = Limiter(get_remote_address, app=app, default_limits=["5 per second", "30 per minute"])

app.logger.info(f"Environment: {env}")


@app.before_request
def before_request():
    """Execute before requests."""
    # http -> https
    scheme = request.headers.get("X-Forwarded-Proto")
    if scheme and scheme == "http" and request.url.startswith("http://"):
        url = request.url.replace("http://", "https://", 1)
        return redirect(url, code=301)
    # set user
    g.user = None
    if "user_id" in session:
        g.user = User.query.get(session["user_id"])
