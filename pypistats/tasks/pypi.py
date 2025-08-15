"""Get the download stats for a specific day."""

import datetime
import os
import sqlite3
import tempfile
import time
from contextlib import contextmanager

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

# Configurable batch size for processing (default 100,000)
BATCH_SIZE = int(os.environ.get("ETL_BATCH_SIZE", "100000"))


@contextmanager
def get_sqlite_db(date):
    """Create a temporary SQLite database for staging data."""
    # Create temp file in system temp directory
    temp_dir = tempfile.gettempdir()
    db_path = os.path.join(temp_dir, f"pypistats_etl_{date.replace('-', '')}.db")

    print(f"Creating temporary SQLite database: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Performance optimizations for bulk inserts
        cursor.execute("PRAGMA synchronous = OFF")  # Don't wait for disk writes
        cursor.execute("PRAGMA journal_mode = WAL")  # Write-Ahead Logging (faster, less memory)
        cursor.execute("PRAGMA temp_store = FILE")  # Use disk for temp tables to save memory
        cursor.execute("PRAGMA cache_size = -32000")  # 32MB cache to reduce memory usage
        cursor.execute("PRAGMA page_size = 8192")  # Smaller page size for better memory efficiency
        cursor.execute("PRAGMA locking_mode = EXCLUSIVE")  # Exclusive access

        # Create tables matching PostgreSQL structure
        for table in PSQL_TABLES:
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    date TEXT NOT NULL,
                    package TEXT NOT NULL,
                    category TEXT NOT NULL,
                    downloads INTEGER NOT NULL,
                    PRIMARY KEY (date, package, category)
                )
            """
            )

            # Create indexes AFTER bulk inserts for better performance
            # We'll create them later in the process

        conn.commit()
        yield conn, cursor

    finally:
        conn.close()
        # Clean up temp file
        if os.path.exists(db_path):
            os.remove(db_path)
            print(f"Cleaned up temporary database: {db_path}")


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


def process_batch_to_sqlite(cursor, table, rows):
    """Insert a batch of rows into SQLite table."""
    # Filter invalid rows
    valid_rows = []
    for row in rows:
        # Convert None to 'null' string for SQLite compatibility
        # This preserves NULL Python versions which are valid data
        processed_row = []
        for item in row:
            if item is None:
                processed_row.append("null")
            else:
                processed_row.append(item)

        # Skip rows with overly long package names
        if any(len(str(item)) > 128 for item in processed_row[1:2]):  # Check package name only
            continue

        # Skip rows with empty (but not null) python versions for version tables
        if table in ("python_major", "python_minor"):
            if processed_row[2] in ("", "."):
                continue

        valid_rows.append(processed_row)

    if not valid_rows:
        return True

    # SQLite has a limit on number of variables (SQLITE_MAX_VARIABLE_NUMBER)
    # Default is often 999, but can be up to 32766
    # Most modern SQLite builds support 32766 variables
    # With 4 columns per row, we can do 8000 rows at a time (32000 variables)
    # Using 2000 for safety and good performance
    SQLITE_CHUNK_SIZE = 2000

    try:
        # Process in chunks to avoid "too many SQL variables" error
        for i in range(0, len(valid_rows), SQLITE_CHUNK_SIZE):
            chunk = valid_rows[i : i + SQLITE_CHUNK_SIZE]

            # Use executemany for better performance
            cursor.executemany(
                f"INSERT OR REPLACE INTO {table} (date, package, category, downloads) VALUES (?, ?, ?, ?)", chunk
            )
        return True
    except sqlite3.Error as e:
        print(f"Error inserting into SQLite {table}: {e}")
        return False


def transfer_sqlite_to_postgres(sqlite_cursor, date):
    """Transfer all data from SQLite to PostgreSQL in a single atomic transaction."""
    pg_conn, pg_cursor = get_connection_cursor()

    # Smaller chunk size to reduce memory usage
    # 10k rows is more manageable and still efficient
    TRANSFER_CHUNK_SIZE = 10000

    try:
        # Start transaction
        pg_conn.autocommit = False

        print("Starting PostgreSQL transaction...")

        # For each table, delete old data and insert new data
        for table in PSQL_TABLES:
            # First, count the rows to transfer
            sqlite_cursor.execute(
                f"SELECT COUNT(*) FROM {table} WHERE date = ?",
                (date,),
            )
            total_rows = sqlite_cursor.fetchone()[0]

            if total_rows > 0:
                print(f"Transferring {total_rows:,} rows to PostgreSQL {table}...")

                # Delete existing data for this date
                pg_cursor.execute(f"DELETE FROM {table} WHERE date = %s", (date,))

                # Stream data in chunks to avoid loading all into memory
                offset = 0
                chunks_transferred = 0

                while offset < total_rows:
                    # Get a chunk of data from SQLite
                    sqlite_cursor.execute(
                        f"""
                        SELECT date, package, category, downloads 
                        FROM {table} 
                        WHERE date = ?
                        ORDER BY package, category
                        LIMIT ? OFFSET ?
                        """,
                        (date, TRANSFER_CHUNK_SIZE, offset),
                    )
                    chunk = sqlite_cursor.fetchall()

                    if not chunk:
                        break

                    # Insert this chunk into PostgreSQL
                    insert_query = f"""
                        INSERT INTO {table} (date, package, category, downloads)
                        VALUES %s
                    """
                    # Smaller page_size to reduce memory usage when building SQL
                    execute_values(pg_cursor, insert_query, chunk, page_size=1000)

                    chunks_transferred += 1
                    offset += TRANSFER_CHUNK_SIZE

                    # Report progress every 50 chunks (500k rows with 10k chunks)
                    if chunks_transferred % 50 == 0:
                        print(f"  Transferred {offset:,}/{total_rows:,} rows...")

        # Commit the transaction - all tables update atomically
        pg_conn.commit()
        print("PostgreSQL transaction committed successfully!")

        return True

    except psycopg2.Error as e:
        print(f"Error during PostgreSQL transfer: {e}")
        pg_conn.rollback()
        return False

    finally:
        pg_conn.autocommit = True
        pg_conn.close()


def get_daily_download_stats_sqlite(date):
    """Stream BigQuery data into SQLite, then transfer to PostgreSQL atomically."""
    start = time.time()

    if date is None:
        date = str(datetime.date.today() - datetime.timedelta(days=1))

    with get_sqlite_db(date) as (sqlite_conn, sqlite_cursor):
        # Stream from BigQuery into SQLite
        job_config = bigquery.QueryJobConfig()
        credentials, project_id = get_google_credentials()
        bq_client = bigquery.Client(project=project_id, credentials=credentials)

        print(f"Date: {date}")
        print("Sending query to BigQuery...")
        query = get_query(date)
        query_job = bq_client.query(query, job_config=job_config)
        iterator = query_job.result()
        print(f"Streaming to SQLite (batch size: {BATCH_SIZE})")

        batch_data = {}
        row_count = 0
        batches_processed = 0

        for row in iterator:
            row_count += 1

            category_label = row["category_label"]
            if category_label not in batch_data:
                batch_data[category_label] = []

            batch_data[category_label].append([date, row["package"], row["category"], row["downloads"]])

            # Process batch when it reaches size limit
            if len(batch_data[category_label]) >= BATCH_SIZE:
                batches_processed += 1
                print(f"Writing batch {batches_processed} to SQLite ({category_label}: {BATCH_SIZE} rows)")
                process_batch_to_sqlite(sqlite_cursor, category_label, batch_data[category_label])
                batch_data[category_label] = []

            if row_count % 1000000 == 0:
                sqlite_conn.commit()  # Less frequent commits for better performance
                print(f"Processed {row_count} rows into SQLite...")

        # Process remaining batches
        for category_label, rows in batch_data.items():
            if rows:
                print(f"Writing final batch to SQLite ({category_label}: {len(rows)} rows)")
                process_batch_to_sqlite(sqlite_cursor, category_label, rows)

        sqlite_conn.commit()
        print(f"SQLite staging complete: {row_count} rows in {batches_processed} batches")

        # Create indexes now for faster aggregation
        print("Creating indexes for aggregation...")
        for table in PSQL_TABLES:
            sqlite_cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_date ON {table} (date)")
            sqlite_cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_package ON {table} (package)")
        sqlite_conn.commit()

        # Add __all__ aggregations in SQLite
        print("Computing __all__ aggregations in SQLite...")
        for table in PSQL_TABLES:
            sqlite_cursor.execute(
                f"""
                INSERT OR REPLACE INTO {table} (date, package, category, downloads)
                SELECT 
                    date,
                    '__all__' AS package,
                    category,
                    SUM(downloads) AS downloads
                FROM {table}
                WHERE date = ? AND package != '__all__'
                GROUP BY date, category
            """,
                (date,),
            )
        sqlite_conn.commit()

        # Now transfer everything to PostgreSQL in a single transaction
        print("Starting atomic transfer to PostgreSQL...")
        transfer_success = transfer_sqlite_to_postgres(sqlite_cursor, date)

        elapsed = time.time() - start
        return {
            "success": transfer_success,
            "rows_processed": row_count,
            "batches_processed": batches_processed,
            "elapsed": elapsed,
        }


def get_daily_download_stats(date):
    """Get daily download stats for pypi packages from BigQuery."""
    start = time.time()
    connection, cursor = get_connection_cursor()

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
    print("Streaming results with batch processing.")
    print(f"Batch size: {BATCH_SIZE}")

    # Clear existing data for this date first
    for table in PSQL_TABLES:
        cursor.execute(f"DELETE FROM {table} WHERE date = %s", (date,))
    connection.commit()

    batch_data = {}
    row_count = 0
    batches_processed = 0
    results = {}

    for row in iterator:  # Stream directly, no list()
        row_count += 1

        category_label = row["category_label"]
        if category_label not in batch_data:
            batch_data[category_label] = []
            results[category_label] = True

        batch_data[category_label].append([date, row["package"], row["category"], row["downloads"]])

        # Process batch when it reaches size limit
        if len(batch_data[category_label]) >= BATCH_SIZE:
            batches_processed += 1
            print(f"Processing batch {batches_processed} for {category_label} ({BATCH_SIZE} rows)")
            success = update_table(connection, cursor, category_label, batch_data[category_label], date=None)
            results[category_label] = results[category_label] and success
            batch_data[category_label] = []  # Clear batch to free memory

        if row_count % 100000 == 0:
            print(f"Processed {row_count} rows...")

    # Process remaining rows
    for category_label, rows in batch_data.items():
        if rows:
            print(f"Processing final batch for {category_label} ({len(rows)} rows)")
            success = update_table(connection, cursor, category_label, rows, date=None)
            results[category_label] = results[category_label] and success

    connection.close()
    print(f"Total: {row_count} rows from gbq, {batches_processed} batches processed")
    print("Elapsed: " + str(time.time() - start))
    results["elapsed"] = time.time() - start
    results["rows_processed"] = row_count
    results["batches_processed"] = batches_processed
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

    # Only delete if date is provided (for backward compatibility)
    if date:
        delete_query = f"""DELETE FROM {table}
                WHERE date = '{date}'"""
        print(delete_query)
        cursor.execute(delete_query)

    insert_query = f"""INSERT INTO {table} (date, package, category, downloads)
            VALUES %s"""

    try:
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
                FROM {table} where date = %s GROUP BY date, category"""
        print(f"Aggregating {table} for date {date}")
        cursor.execute(aggregate_query, (date,))
        values = cursor.fetchall()
        print(f"Found {len(values)} categories to aggregate for {table}")

        delete_query = f"""DELETE FROM {table}
                WHERE date = %s and package = '__all__'"""
        insert_query = f"""INSERT INTO {table} (date, package, category, downloads)
                VALUES %s"""
        try:
            print(delete_query)
            cursor.execute(delete_query, (date,))
            print(insert_query)
            if values:  # Only insert if there are values
                execute_values(cursor, insert_query, values)
                print(f"Inserted {len(values)} __all__ records into {table}")
            connection.commit()
            success[table] = True
        except psycopg2.IntegrityError as e:
            print(f"Error updating __all__ for {table}: {e}")
            connection.rollback()
            success[table] = False

    connection.close()
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
def etl(date=None, purge=True, use_sqlite=True, update_recent=True):
    """
    Perform the stats download.

    Args:
        date: Date to process (YYYY-MM-DD format)
        purge: Whether to purge old data
        use_sqlite: Use SQLite staging for atomic updates (recommended)
        update_recent: Whether to update recent stats table (set False for backfill)
    """
    if date is None:
        date = str(datetime.date.today() - datetime.timedelta(days=1))

    results = dict()

    if use_sqlite:
        # Use SQLite staging for zero-downtime atomic updates
        print("Using SQLite staging for atomic updates")
        results["downloads"] = get_daily_download_stats_sqlite(date)
        # __all__ stats are already computed in SQLite
    else:
        # Use original streaming approach (partial data visible during ETL)
        print("Using direct streaming (partial data may be visible)")
        results["downloads"] = get_daily_download_stats(date)
        results["__all__"] = update_all_package_stats(date)

    if update_recent:
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
