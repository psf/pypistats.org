"""Functional coverage of the API, rendered pages, and PostgreSQL update path."""

import datetime
import json
import re
from unittest.mock import Mock

import pytest
import requests


def get_json(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response.mimetype == "application/json"
    return response.json


def assert_package_page(client, date, day, week, month):
    response = client.get("/packages/sample-package")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "<h1>sample-package</h1>" in html
    for period, downloads in [("day", day), ("week", week), ("month", month)]:
        assert f"Downloads last {period}: {downloads:,}" in re.sub(r"\s+", " ", html)
    plots, _ = json.JSONDecoder().raw_decode(html.split("var data =", 1)[1].lstrip())
    assert len(plots) == 7
    overall = {trace["name"]: trace for trace in plots[0]["data"]}
    assert overall["Without_Mirrors"]["x"][-1] == str(date)
    assert overall["Without_Mirrors"]["y"][-1] == day
    return html


@pytest.mark.parametrize(
    "query,data",
    [
        ("", {"last_day": 10, "last_week": 30, "last_month": 30}),
        ("?period=day", {"last_day": 10}),
        ("?period=week", {"last_week": 30}),
        ("?period=month", {"last_month": 30}),
    ],
)
def test_recent_api(client, query, data):
    assert get_json(client, f"/api/packages/sample_package/recent{query}") == {
        "package": "sample-package",
        "type": "recent_downloads",
        "data": data,
    }


@pytest.mark.parametrize(
    "endpoint,query,category,multiplier",
    [
        ("overall", "mirrors=false", "without_mirrors", 1),
        ("overall", "mirrors=true", "with_mirrors", 2),
        ("python_major", "version=3", "3", 1),
        ("python_minor", "version=3.13", "3.13", 1),
        ("system", "os=linux", "Linux", 1),
    ],
)
def test_history_apis(client, date, endpoint, query, category, multiplier):
    assert get_json(client, f"/api/packages/sample.package/{endpoint}?{query}") == {
        "package": "sample-package",
        "type": f"{endpoint}_downloads",
        "data": [
            {"date": str(date - datetime.timedelta(days=1)), "category": category, "downloads": 20 * multiplier},
            {"date": str(date), "category": category, "downloads": 10 * multiplier},
        ],
    }


def test_history_categories(client):
    rows = get_json(client, "/api/packages/sample-package/overall")["data"]
    assert len(rows) == 4
    assert {row["category"] for row in rows} == {"with_mirrors", "without_mirrors"}
    assert get_json(client, "/api/packages/sample-package/system?os=windows")["data"] == []


@pytest.mark.parametrize(
    "path",
    [
        "/api/packages/missing/recent",
        "/api/packages/missing/overall",
        "/api/packages/sample-package/recent?period=year",
    ],
)
def test_api_errors(client, path):
    assert client.get(path).status_code == 404


@pytest.mark.parametrize(
    "path,content",
    [
        ("/", "Analytics for PyPI packages"),
        ("/about", "About PyPI Stats"),
        ("/faqs", "<h1>FAQs</h1>"),
        ("/api/", "PyPI Stats API"),
        ("/top", "Most downloaded PyPI packages"),
        ("/health", "OK"),
        ("/_health/", "OK"),
        ("/status", "OK"),
    ],
)
def test_public_pages(client, path, content):
    response = client.get(path)
    assert response.status_code == 200
    assert content in response.get_data(as_text=True)


def test_search_and_top_packages(client):
    response = client.post("/", data={"name": "SAMPLE.PACKAGE"}, follow_redirects=True)
    assert response.status_code == 200
    assert response.request.path == "/packages/sample-package"
    assert b"<h1>sample-package</h1>" in response.data
    results = client.get("/search/sample").text
    assert 'href="/packages/sample-package"' in results
    assert 'href="/packages/sample-other"' in results
    missing = client.get("/packages/missing", follow_redirects=True)
    assert missing.request.path == "/search/missing"
    assert "No results." in missing.text
    top = client.get("/top").text.split("<section>", 1)[1]
    assert top.index('href="/packages/sample-other"') < top.index('href="/packages/sample-package"')
    assert 'href="/packages/__all__"' not in top


def test_package_metadata_and_charts(client, date):
    html = assert_package_page(client, date, 10, 30, 30)
    assert "Author: Doe, Jane" in re.sub(r"\s+", " ", html)
    for content in [
        "A sample &lt;package&gt; &amp; its tools",
        'href="https://example.org/"',
        'href="/packages/requests"',
        'href="/packages/pytest"',
        "1.2.3",
    ]:
        assert content in html


def test_pypi_unavailable(client, date, pypi_request):
    pypi_request.side_effect = requests.Timeout("PyPI unavailable")
    assert "No metadata found." in assert_package_page(client, date, 10, 30, 30)
    response = client.get("/packages/sample-package?smooth=true")
    assert response.status_code == 200
    assert "No metadata found." in response.get_data(as_text=True)


def test_all_packages_page(client, pypi_request):
    response = client.get("/packages/__all__")
    assert response.status_code == 200
    assert "downloads across all packages on PyPI" in response.text
    pypi_request.assert_not_called()


def test_admin_auth_and_submission(client, date, monkeypatch):
    enqueue = Mock()
    monkeypatch.setattr("pypistats.views.admin.etl.apply_async", enqueue)
    assert client.post("/admin", data={"date": str(date)}).status_code == 401
    assert client.get("/admin", auth=("test", "wrong-password")).status_code == 401
    assert client.post("/admin", data={"date": "invalid"}, auth=("test", "test-password")).status_code == 200
    enqueue.assert_not_called()
    response = client.post("/admin", data={"date": str(date)}, auth=("test", "test-password"))
    assert response.status_code == 200
    assert f"{date} submitted." in response.text
    enqueue.assert_called_once_with(args=(str(date),))


def test_update_reaches_api_ui_and_totals_and_can_be_rerun(client, date, update):
    assert get_json(client, "/api/packages/sample-package/recent")["data"]["last_day"] == 10
    for downloads, minor, system in [
        (80, "3.12", "Windows"),
        (80, "3.12", "Windows"),
        (3_000_000_000, "3.11", "Darwin"),
    ]:
        update(downloads, minor, system)
        assert get_json(client, "/api/packages/sample-package/recent")["data"] == {
            "last_day": downloads,
            "last_week": downloads + 20,
            "last_month": downloads + 20,
        }
        assert get_json(client, "/api/packages/__all__/recent")["data"] == {
            "last_day": downloads + 20,
            "last_week": downloads + 40,
            "last_month": downloads + 40,
        }
        # Every old and new category must be right, including __all__ and the
        # previous day. Switching categories on the last rerun must remove stale rows.
        for endpoint, (previous, current) in {
            "overall": (
                {"without_mirrors": 20, "with_mirrors": 40},
                {"without_mirrors": (downloads, downloads + 20), "with_mirrors": (downloads + 20, downloads + 60)},
            ),
            "python_major": ({"3": 20}, {"3": (downloads - 7, downloads + 13), "null": (7, 7)}),
            "python_minor": ({"3.13": 20}, {"3.13": (downloads - 12, downloads + 8), minor: (5, 5), "null": (7, 7)}),
            "system": ({"Linux": 20}, {"Linux": (downloads - 11, downloads + 9), system: (8, 8), "other": (3, 3)}),
        }.items():
            for index, package in enumerate(["sample-package", "__all__"]):
                rows = get_json(client, f"/api/packages/{package}/{endpoint}")["data"]
                expected = {
                    (str(date - datetime.timedelta(days=1)), category): count for category, count in previous.items()
                }
                expected.update({(str(date), category): counts[index] for category, counts in current.items()})
                assert {(row["date"], row["category"]): row["downloads"] for row in rows} == expected
        assert_package_page(client, date, downloads, downloads + 20, downloads + 20)


def test_direct_streaming_updates_batches_and_aggregates(client, date, pypi, bigquery):
    columns = {"package": 0, "category_label": 1, "category": 2, "downloads": 3}
    for downloads in [3_000_000_000, 50]:
        rows = [
            ("sample-package", table, category, downloads)
            for table, category in zip(pypi.PSQL_TABLES, ["without_mirrors", "3", "3.13", "Linux"])
        ]
        rows.extend((f"other-{count}", "overall", "without_mirrors", count) for count in [1, 2, 3])
        bigquery.return_value = iter(pypi.bigquery.Row(row, columns) for row in rows)
        result = pypi.etl.apply(args=(str(date),), kwargs={"use_sqlite": False}, throw=True).get()
        assert result["downloads"]["batches_processed"] > 0
        assert all(result["downloads"][table] for table in pypi.PSQL_TABLES)
        assert all(result["__all__"][table] for table in pypi.PSQL_TABLES)
        assert get_json(client, "/api/packages/sample-package/recent")["data"]["last_day"] == downloads
        assert get_json(client, "/api/packages/__all__/recent")["data"]["last_day"] == downloads + 6


def test_retention_boundary(postgresql, date, update, pypi):
    cutoff = date - datetime.timedelta(days=180)
    for day in [cutoff - datetime.timedelta(days=1), cutoff]:
        for table, category in zip(pypi.PSQL_TABLES, ["without_mirrors", "3", "3.13", "Linux"]):
            postgresql.execute(f"INSERT INTO {table} VALUES (%s, %s, %s, %s)", (day, "old-package", category, 1))
    postgresql.commit()
    result = update()
    for table in pypi.PSQL_TABLES:
        assert result["purge"][table]
        assert postgresql.execute(f"SELECT date FROM {table} WHERE package = 'old-package'").fetchall() == [(cutoff,)]


def test_recent_period_boundaries(client, postgresql, date, pypi):
    for days_ago, downloads in [(6, 3), (7, 5), (29, 7), (30, 11)]:
        postgresql.execute(
            "INSERT INTO overall VALUES (%s, %s, %s, %s)",
            (
                date - datetime.timedelta(days=days_ago),
                "sample-package",
                "without_mirrors",
                downloads,
            ),
        )
    postgresql.commit()
    pypi.update_recent_stats(str(date))
    assert get_json(client, "/api/packages/sample-package/recent")["data"] == {
        "last_day": 10,
        "last_week": 33,
        "last_month": 45,
    }


def test_failed_transfer_rolls_back_all_tables(client, date, pypi):
    with pypi.get_sqlite_db(str(date)) as (connection, cursor):
        cursor.execute("INSERT INTO overall VALUES (?, ?, ?, ?)", (str(date), "sample-package", "without_mirrors", 999))
        # PostgreSQL rejects this after updating overall, exercising the rollback.
        cursor.execute("INSERT INTO python_major VALUES (?, ?, ?, ?)", (str(date), "sample-package", "too-long", 999))
        connection.commit()
        assert not pypi.transfer_sqlite_to_postgres(cursor, str(date))
    for endpoint in ["overall?mirrors=false", "python_major", "python_minor", "system"]:
        assert [row["downloads"] for row in get_json(client, f"/api/packages/sample-package/{endpoint}")["data"]] == [
            20,
            10,
        ]
    assert_package_page(client, date, 10, 30, 30)


def test_failed_import_preserves_data(client, date, pypi, bigquery):
    bigquery.side_effect = RuntimeError("BigQuery unavailable")
    with pytest.raises(RuntimeError, match="BigQuery unavailable"):
        pypi.etl.apply(args=(str(date),), throw=True)
    assert get_json(client, "/api/packages/sample-package/recent")["data"]["last_day"] == 10
    assert_package_page(client, date, 10, 30, 30)
