"""PyPIStats application."""

from celery import Task
from flask import Flask

from pypistats import views
from pypistats.config import DevConfig
from pypistats.extensions import celery
from pypistats.extensions import db
from pypistats.extensions import github
from pypistats.extensions import migrate


def create_app(config_object=DevConfig):
    """Create the application."""
    app = Flask(__name__.split(".")[0])
    app.config.from_object(config_object)
    register_extensions(app)
    register_blueprints(app)
    init_celery(celery, app)
    return app


def init_celery(celery_, app):
    """Create a celery object."""
    celery_.conf.update(app.config)

    class ContextTask(Task):
        abstract = True

        def __call__(self, *args, **kwargs):
            with app.app_context():
                return Task.__call__(self, *args, **kwargs)

    celery_.Task = ContextTask


def register_blueprints(app):
    """Register Flask blueprints."""
    app.register_blueprint(views.admin.blueprint)
    app.register_blueprint(views.api.blueprint)
    app.register_blueprint(views.error.blueprint)
    app.register_blueprint(views.general.blueprint)
    app.register_blueprint(views.user.blueprint)


def register_extensions(app):
    """Register Flask extensions."""
    db.init_app(app)
    github.init_app(app)
    migrate.init_app(app, db)
