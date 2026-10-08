"""Application fixtures; pytest plugins own the client and database lifecycle."""

import datetime
import uuid
from copy import deepcopy
from unittest.mock import Mock
from unittest.mock import create_autospec

import pytest
from flask_migrate import upgrade
from pytest_postgresql import factories
from sqlalchemy.engine import URL

postgresql_server = factories.postgresql_noproc(dbname="pypistats_test_" + uuid.uuid4().hex)
postgresql = factories.postgresql("postgresql_server")


@pytest.fixture
def app(postgresql, postgresql_server, monkeypatch):
    database_url = URL.create(
        "postgresql",
        username=postgresql.info.user,
        password=postgresql_server.password,
        host=postgresql.info.host,
        port=postgresql.info.port,
        database=postgresql.info.dbname,
    ).render_as_string(hide_password=False)
    for key, value in {
        "DATABASE_URL": database_url,
        "REDIS_URL": "memory://",
        "ENV": "test",
        "BASIC_AUTH_USER": "test",
        "BASIC_AUTH_PASSWORD": "test-password",
        "PYPISTATS_SECRET": "functional-tests",
    }.items():
        monkeypatch.setenv(key, value)

    from pypistats.extensions import db
    from pypistats.run import app

    # Reject an app imported with another database before touching its schema.
    assert app.config["SQLALCHEMY_DATABASE_URI"] == database_url
    with app.app_context():
        upgrade()
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def date():
    return datetime.date.today() - datetime.timedelta(days=1)


@pytest.fixture(autouse=True)
def sample_data(app, date):
    from pypistats.extensions import db
    from pypistats.models.download import RecentDownloadCount
    from pypistats.views.general import MODELS

    for package, counts in {
        "sample-package": [(date - datetime.timedelta(days=1), 20), (date, 10)],
        "sample-other": [(date, 40)],
        "__all__": [(date - datetime.timedelta(days=1), 20), (date, 50)],
    }.items():
        for day, downloads in counts:
            for model, category in zip(MODELS, ["without_mirrors", "3", "3.13", "Linux"]):
                db.session.add(model(package=package, date=day, category=category, downloads=downloads))
            db.session.add(MODELS[0](package=package, date=day, category="with_mirrors", downloads=downloads * 2))
        for period in ["day", "week", "month"]:
            downloads = counts[-1][1] if period == "day" else sum(count for _, count in counts)
            db.session.add(RecentDownloadCount(package=package, category=period, downloads=downloads))
    db.session.commit()


@pytest.fixture(autouse=True)
def pypi_request(app, monkeypatch):
    metadata = {
        "info": {
            "package_url": "https://pypi.org/project/sample-package/",
            "home_page": None,
            "project_urls": {"Homepage": "https://example.org/"},
            "author": None,
            "author_email": '"Doe, Jane" <jane@example.org>',
            "license": "MIT",
            "summary": "A sample <package> & its tools",
            "version": "1.2.3",
            "requires_dist": ["requests>=2", 'pytest; extra == "test"'],
        }
    }
    get = Mock(return_value=Mock(json=lambda: deepcopy(metadata)))
    monkeypatch.setattr("pypistats.views.general.requests.get", get)
    monkeypatch.setattr(
        "requests.sessions.Session.request", Mock(side_effect=AssertionError("Unexpected external HTTP request"))
    )
    return get


@pytest.fixture
def pypi(app, tmp_path, monkeypatch):
    from pypistats.tasks import pypi

    monkeypatch.setattr(pypi.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(pypi, "get_google_credentials", lambda: (None, "test-project"))
    monkeypatch.setattr(pypi, "BATCH_SIZE", 3)
    return pypi


@pytest.fixture
def bigquery(pypi, monkeypatch):
    client = create_autospec(pypi.bigquery.Client, spec_set=True)
    job = create_autospec(pypi.bigquery.QueryJob, instance=True, spec_set=True)
    client.return_value.query.return_value = job
    monkeypatch.setattr(pypi.bigquery, "Client", client)
    return job.result


@pytest.fixture
def update(pypi, bigquery, date):
    def run(downloads=80, minor="3.12", system="Windows"):
        # Interleaved categories include full and partial batches. Invalid records
        # must not stop valid records from reaching the API or inflate __all__.
        rows = [
            ("sample-package", "overall", "without_mirrors", downloads),
            ("sample-package", "overall", "with_mirrors", downloads + 20),
            ("sample-package", "python_major", "3", downloads - 7),
            ("sample-package", "python_minor", "3.13", downloads - 12),
            ("sample-package", "system", "Linux", downloads - 11),
            ("sample-other", "overall", "without_mirrors", 20),
            ("sample-other", "overall", "with_mirrors", 40),
            ("sample-other", "python_major", "3", 20),
            ("sample-other", "python_minor", "3.13", 20),
            ("sample-other", "system", "Linux", 20),
            ("sample-package", "python_major", None, 7),
            ("sample-package", "python_minor", minor, 5),
            ("sample-package", "python_minor", None, 7),
            ("sample-package", "system", system, 8),
            ("sample-package", "system", "other", 3),
            ("sample-package", "python_major", "", 1),
            ("sample-package", "python_minor", ".", 1),
            ("sample-package", "python_minor", "3.100", 1),
            ("x" * 129, "overall", "without_mirrors", 1),
        ]
        columns = {"package": 0, "category_label": 1, "category": 2, "downloads": 3}
        bigquery.return_value = iter(pypi.bigquery.Row(values, columns) for values in rows)
        result = pypi.etl.apply(args=(str(date),), throw=True).get()
        assert result["downloads"]["success"]
        assert result["downloads"]["rows_processed"] == len(rows)
        assert result["downloads"]["batches_processed"] > 0
        assert all(result["recent"][period] for period in ["day", "week", "month"])
        return result

    return run
