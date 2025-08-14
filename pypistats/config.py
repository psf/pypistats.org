"""Application configuration."""

import os

from celery.schedules import crontab
from flask import json


def get_db_uri():
    """Get the database URI."""
    return os.environ.get("DATABASE_URL")


class Config:
    """Base configuration."""

    APP_DIR = os.path.abspath(os.path.dirname(__file__))
    # Celery 5.x configuration
    broker_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    broker_transport_options = {"visibility_timeout": 86400}
    imports = ["pypistats.tasks.pypi"]
    beat_schedule = {
        "update_db": {"task": "pypistats.tasks.pypi.etl", "schedule": crontab(minute=0, hour=1)}  # 1am UTC
    }
    # Use RedBeat scheduler to store schedule in Redis instead of filesystem
    beat_scheduler = "redbeat.RedBeatScheduler"
    # RedBeat uses the same Redis as the broker by default
    redbeat_redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID")
    GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET")
    PROJECT_ROOT = os.path.abspath(os.path.join(APP_DIR, os.pardir))
    SECRET_KEY = os.environ.get("PYPISTATS_SECRET", "secret-key")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_DATABASE_URI = get_db_uri()

    # Plotly chart definitions
    PLOT_BASE = json.load(open(os.path.join(os.path.dirname(__file__), "plots", "plot_base.json")))
    DATA_BASE = json.load(open(os.path.join(os.path.dirname(__file__), "plots", "data_base.json")))


class LocalConfig(Config):
    """Local configuration."""

    DEBUG = True
    ENV = "local"


class ProdConfig(Config):
    """Production configuration."""

    DEBUG = False
    ENV = "prod"


class DevConfig(Config):
    """Development configuration."""

    DEBUG = True
    ENV = "dev"


class TestConfig(Config):
    """Test configuration."""

    DEBUG = True
    ENV = "dev"
    TESTING = True
    WTF_CSRF_ENABLED = False  # Allows form testing


configs = {"development": DevConfig, "local": LocalConfig, "production": ProdConfig, "test": TestConfig}
