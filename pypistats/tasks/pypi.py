"""Get the download stats for a specific day."""

import datetime
import os
import time

import psycopg2
from google.cloud import bigquery
from psycopg2.extras import execute_values

from pypistats.extensions import celery

# Mirrors to disregard when considering downloads
MIRRORS = ("bandersnatch", "z3c.pypimirror", "Artifactory", "devpi")

# PyPI systems
SYSTEMS = ("Windows", "Linux", "Darwin")

# postgresql tables to update for __all__
PSQL_TABLES = ["overall", "python_major", "python_minor", "system"]

# Number of days to retain records
MAX_RECORD_AGE = 180


def get_google_credentials():
    """Obtain the Google credentials and project ID from service account JSON."""
    import json

    from google.oauth2 import service_account

    # Use service account JSON provided as a single environment variable
    service_account_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not service_account_json:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON environment variable is required")

    service_account_info = json.loads(service_account_json)
    credentials = service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=["https://www.googleapis.com/auth/bigquery", "https://www.googleapis.com/auth/cloud-platform"],
    )
    project_id = service_account_info.get("project_id")
    if not project_id:
        raise ValueError("project_id not found in service account JSON")
    return credentials, project_id


def get_daily_download_stats(date):
    """Get daily download stats for pypi packages from BigQuery."""
    start = time.time()

    job_config = bigquery.QueryJobConfig()
    credentials, project_id = get_google_credentials()
    bq_client = bigquery.Client(project=project_id, credentials=credentials)
    if date is None:
        date = str(datetime.date.today() - datetime.timedelta(days=1))

    print(date)
    print("Sending query to BigQuery...")
    query = get_query(date)
    print(query)
    print("Sent.")
    query_job = bq_client.query(query, job_config=job_config)
    iterator = query_job.result()
    print("Downloading results.")
    rows = list(iterator)
    print(len(rows), "rows from gbq")

    data = {}
    for row in rows:
        if row["category_label"] not in data:
            data[row["category_label"]] = []
        data[row["category_label"]].append([date, row["package"], row["category"], row["downloads"]])

    results = update_db(data, date)
    print("Elapsed: " + str(time.time() - start))
    results["elapsed"] = time.time() - start
    return results


def update_db(data, date=None):
    """Update the db with new data by table."""
    connection, cursor = get_connection_cursor()

    success = {}
    for category_label, rows in data.items():
        table = category_label
        success[table] = update_table(connection, cursor, table, rows, date)

    return success


def update_table(connection, cursor, table, rows, date):
    """Update a table."""
    print(table)

    delete_rows = []
    for row_idx, row in enumerate(rows):
        for idx, item in enumerate(row):
            if item is None:
                row[idx] = "null"
            else:
                # Some hacky packages have long names; ignore them
                if len(str(item)) > 128:
                    delete_rows.append(row_idx)
                    print(row)

    # Some packages have installs with empty (non-null) python version; ignore
    if table in ("python_major", "python_minor"):
        for idx, row in enumerate(rows):
            if row[2] in ("", "."):
                delete_rows.append(idx)
                print(row)

    print(delete_rows)
    # Delete ignored rows
    for idx in sorted(delete_rows, reverse=True):
        rows.pop(idx)

    delete_query = f"""DELETE FROM {table}
            WHERE date = '{date}'"""
    insert_query = f"""INSERT INTO {table} (date, package, category, downloads)
            VALUES %s"""

    try:
        print(delete_query)
        cursor.execute(delete_query)
        print(insert_query)
        execute_values(cursor, insert_query, rows)
        connection.commit()
        return True
    except psycopg2.IntegrityError as e:
        connection.rollback()
        return False


def update_all_package_stats(date=None):
    """Update stats for __all__ packages."""
    print("__all__")
    start = time.time()

    if date is None:
        date = str(datetime.date.today() - datetime.timedelta(days=1))

    connection, cursor = get_connection_cursor()

    success = {}
    for table in PSQL_TABLES:
        aggregate_query = f"""SELECT date, '__all__' AS package, category, sum(downloads) AS downloads
                FROM {table} where date = '{date}' GROUP BY date, category"""
        cursor.execute(aggregate_query, (table,))
        values = cursor.fetchall()

        delete_query = f"""DELETE FROM {table}
                WHERE date = '{date}' and package = '__all__'"""
        insert_query = f"""INSERT INTO {table} (date, package, category, downloads)
                VALUES %s"""
        try:
            print(delete_query)
            cursor.execute(delete_query)
            print(insert_query)
            execute_values(cursor, insert_query, values)
            connection.commit()
            success[table] = True
        except psycopg2.IntegrityError as e:
            connection.rollback()
            success[table] = False

    print("Elapsed: " + str(time.time() - start))
    success["elapsed"] = time.time() - start
    return success


def update_recent_stats(date=None):
    """Update daily, weekly, monthly stats for all packages."""
    print("recent")
    start = time.time()

    if date is None:
        date = str(datetime.date.today() - datetime.timedelta(days=1))

    connection, cursor = get_connection_cursor()

    downloads_table = "overall"
    recent_table = "recent"

    date = datetime.datetime.strptime(date, "%Y-%m-%d").date()
    date_week = date - datetime.timedelta(days=7)
    date_month = date - datetime.timedelta(days=30)

    where = {
        "day": f"date = '{str(date)}'",
        "week": f"date > '{str(date_week)}'",
        "month": f"date > '{str(date_month)}'",
    }

    success = {}
    for period, clause in where.items():
        select_query = f"""SELECT package, '{period}' as category, sum(downloads) AS downloads
                FROM {downloads_table}
                WHERE category = 'without_mirrors' and {clause}
                GROUP BY package"""
        cursor.execute(select_query)
        values = cursor.fetchall()

        delete_query = f"""DELETE FROM {recent_table}
                WHERE category = '{period}'"""
        insert_query = f"""INSERT INTO {recent_table}
               (package, category, downloads) VALUES %s"""
        try:
            print(delete_query)
            cursor.execute(delete_query)
            print(insert_query)
            execute_values(cursor, insert_query, values)
            connection.commit()
            success[period] = True
        except psycopg2.IntegrityError as e:
            connection.rollback()
            success[period] = False

    print("Elapsed: " + str(time.time() - start))
    success["elapsed"] = time.time() - start
    return success


def get_connection_cursor():
    """Get a db connection cursor."""
    connection = psycopg2.connect(os.environ["DATABASE_URL"])
    cursor = connection.cursor()
    return connection, cursor


def purge_old_data(date=None):
    """Purge old data records."""
    print("Purge")
    age = MAX_RECORD_AGE
    start = time.time()

    if date is None:
        date = str(datetime.date.today() - datetime.timedelta(days=1))

    connection, cursor = get_connection_cursor()

    date = datetime.datetime.strptime(date, "%Y-%m-%d")
    purge_date = date - datetime.timedelta(days=age)
    purge_date = purge_date.strftime("%Y-%m-%d")

    success = {}
    for table in PSQL_TABLES:
        delete_query = f"""DELETE FROM {table} where date < '{purge_date}'"""
        try:
            print(delete_query)
            cursor.execute(delete_query)
            connection.commit()
            success[table] = True
        except psycopg2.IntegrityError as e:
            connection.rollback()
            success[table] = False

    print("Elapsed: " + str(time.time() - start))
    success["elapsed"] = time.time() - start
    return success


def vacuum_analyze():
    """Vacuum and analyze the db."""
    connection, cursor = get_connection_cursor()
    connection.set_isolation_level(0)

    results = {}
    start = time.time()
    cursor.execute("VACUUM")
    results["vacuum"] = time.time() - start

    start = time.time()
    cursor.execute("ANALYZE")
    results["analyze"] = time.time() - start

    print(results)
    return results


def get_query(date):
    """Get the query to execute against pypistats on bigquery."""
    return f"""
    WITH
      dls AS (
      SELECT
        file.project AS package,
        details.installer.name AS installer,
        details.python AS python_version,
        details.system.name AS system
      FROM
        `bigquery-public-data.pypi.file_downloads`
      WHERE
        DATE(timestamp) = '{date}'
      AND
        (REGEXP_CONTAINS(details.python,r'^[0-9]\\.[0-9]+.{{0,}}$') OR
        details.python IS NULL)
      )
    SELECT
      package,
      'python_major' AS category_label,
      cast(SPLIT(python_version, '.')[
    OFFSET
      (0)] as string) AS category,
      COUNT(*) AS downloads
    FROM
      dls
    WHERE
      installer NOT IN {str(MIRRORS)}
    GROUP BY
      package,
      category
    UNION ALL
    SELECT
      package,
      'python_minor' AS category_label,
      REGEXP_EXTRACT(python_version, r'^[0-9]+\\.[0-9]+') AS category,
      COUNT(*) AS downloads
    FROM
      dls
    WHERE
      installer NOT IN {str(MIRRORS)}
    GROUP BY
      package,
      category
    UNION ALL
    SELECT
      package,
      'overall' AS category_label,
      'with_mirrors' AS category,
      COUNT(*) AS downloads
    FROM
      dls
    GROUP BY
      package,
      category
    UNION ALL
    SELECT
      package,
      'overall' AS category_label,
      'without_mirrors' AS category,
      COUNT(*) AS downloads
    FROM
      dls
    WHERE
      installer NOT IN {str(MIRRORS)}
    GROUP BY
      package,
      category
    UNION ALL
    SELECT
      package,
      'system' AS category_label,
      CASE
        WHEN system NOT IN {str(SYSTEMS)} THEN 'other'
        ELSE system
      END AS category,
      COUNT(*) AS downloads
    FROM
      dls
    WHERE
      installer NOT IN {str(MIRRORS)}
    GROUP BY
      package,
      category
    """


@celery.task
def etl(date=None, purge=True):
    """Perform the stats download."""
    if date is None:
        date = str(datetime.date.today() - datetime.timedelta(days=1))
    results = dict()
    results["downloads"] = get_daily_download_stats(date)
    results["__all__"] = update_all_package_stats(date)
    results["recent"] = update_recent_stats()
    results["cleanup"] = vacuum_analyze()
    if purge:
        results["purge"] = purge_old_data(date)
    return results


@celery.task
def example(thing):
    print(thing)
    print("Sleeping")
    time.sleep(10)
    print("done")


if __name__ == "__main__":
    run_date = "2020-01-09"
    print(run_date)
    # print(purge_old_data(run_date))
    # vacuum_analyze()
    print(get_daily_download_stats(run_date))
    print(update_all_package_stats(run_date))
    # print(update_recent_stats(run_date))
    # vacuum_analyze(env)
