"""Flask extensions."""
from celery import Celery
from flask_github import GitHub
from flask_httpauth import HTTPBasicAuth
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

from pypistats.config import Config

db = SQLAlchemy()
github = GitHub()
migrate = Migrate()
auth = HTTPBasicAuth()


def create_celery(name=__name__, config=Config):
    """Create a celery object."""
    celery = Celery(name)
    celery.config_from_object(config)
    return celery


celery = create_celery()
