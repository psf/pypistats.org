"""Backfill range selection and database effects."""

import datetime
from unittest.mock import Mock

import pytest


@pytest.fixture
def backfill(pypi, monkeypatch):
    from pypistats.tasks import backfill

    # Progress reporting needs a Celery result backend; it does not affect imports.
    monkeypatch.setattr(backfill.backfill_sequential, "update_state", Mock())
    return backfill


def daily_rows(pypi, downloads, major="3"):
    columns = {"package": 0, "category_label": 1, "category": 2, "downloads": 3}
    return iter(
        pypi.bigquery.Row(("sample-package", table, category, count), columns)
        for table, category, count in [
            ("overall", "without_mirrors", downloads),
            ("overall", "with_mirrors", downloads + 20),
            ("python_major", major, downloads),
            ("python_minor", "3.13", downloads),
            ("system", "Linux", downloads),
        ]
    )


def test_date_and_month_ranges_include_boundaries(backfill):
    assert backfill.get_date_ranges("2024-02-28", "2024-03-03", chunk_days=2) == [
        ("2024-02-28", "2024-02-29"),
        ("2024-03-01", "2024-03-02"),
        ("2024-03-03", "2024-03-03"),
    ]
    assert backfill.get_month_ranges("2023-12", "2024-02") == [
        ("2023-12-01", "2023-12-31"),
        ("2024-01-01", "2024-01-31"),
        ("2024-02-01", "2024-02-29"),
    ]


def test_backfill_fills_missing_days_skips_existing_and_preserves_history(
    backfill, pypi, bigquery, postgresql, client, date
):
    start = date - datetime.timedelta(days=3)
    old = date - datetime.timedelta(days=500)
    postgresql.execute("INSERT INTO overall VALUES (%s, %s, %s, %s)", (old, "sample-package", "without_mirrors", 7))
    postgresql.commit()
    bigquery.side_effect = [daily_rows(pypi, 30), daily_rows(pypi, 40)]

    result = backfill.backfill_sequential.apply(
        args=(str(start), str(date)), kwargs={"delay_seconds": 0, "skip_existing": True}, throw=True
    ).get()
    for day in (start, start + datetime.timedelta(days=1)):
        assert result[str(day)]["downloads"]["success"]
    for day in (date - datetime.timedelta(days=1), date):
        assert result[str(day)]["skipped"]
    assert bigquery.call_count == 2
    response = client.get("/api/packages/sample-package/overall?mirrors=false")
    assert response.status_code == 200
    assert [(row["date"], row["downloads"]) for row in response.json["data"]] == [
        (str(old), 7),
        (str(start), 30),
        (str(start + datetime.timedelta(days=1)), 40),
        (str(date - datetime.timedelta(days=1)), 20),
        (str(date), 10),
    ]
    assert result["recent_stats_updated"]["day"]
    assert client.get("/api/packages/sample-package/recent").json["data"]["last_day"] == 40


def test_backfill_recent_uses_last_successful_import(backfill, pypi, bigquery, client, date):
    start = date - datetime.timedelta(days=3)
    end = start + datetime.timedelta(days=1)
    # The second day's PostgreSQL transfer fails after staging overall.
    bigquery.side_effect = [daily_rows(pypi, 30), daily_rows(pypi, 900, major="too-long")]

    result = backfill.backfill_sequential.apply(
        args=(str(start), str(end)), kwargs={"delay_seconds": 0}, throw=True
    ).get()
    assert result[str(start)]["downloads"]["success"]
    assert not result[str(end)]["downloads"]["success"]
    assert result["recent_stats_updated"]["day"]
    assert client.get("/api/packages/sample-package/recent").json["data"]["last_day"] == 30
    history = client.get("/api/packages/sample-package/overall?mirrors=false").json["data"]
    assert str(end) not in {row["date"] for row in history}
