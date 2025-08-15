"""Bulk backfill tasks for historical PyPI statistics."""

import datetime
import time
from typing import List
from typing import Optional
from typing import Tuple

from celery import group

from pypistats.extensions import celery
from pypistats.tasks.pypi import etl


def get_date_ranges(start_date: str, end_date: str, chunk_days: int = 30) -> List[Tuple[str, str]]:
    """
    Split a date range into chunks for processing.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        chunk_days: Number of days per chunk (default 30)

    Returns:
        List of (chunk_start, chunk_end) date pairs
    """
    start = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()

    chunks = []
    current = start

    while current <= end:
        chunk_end = min(current + datetime.timedelta(days=chunk_days - 1), end)
        chunks.append((str(current), str(chunk_end)))
        current = chunk_end + datetime.timedelta(days=1)

    return chunks


def get_month_ranges(start_month: str, end_month: str) -> List[Tuple[str, str]]:
    """
    Get calendar month ranges for backfilling.

    Args:
        start_month: Start month in YYYY-MM format
        end_month: End month in YYYY-MM format

    Returns:
        List of (month_start, month_end) date pairs
    """
    from calendar import monthrange

    start_year, start_mon = map(int, start_month.split("-"))
    end_year, end_mon = map(int, end_month.split("-"))

    ranges = []
    current_year = start_year
    current_month = start_mon

    while (current_year < end_year) or (current_year == end_year and current_month <= end_mon):
        # Get first and last day of month
        last_day = monthrange(current_year, current_month)[1]
        month_start = f"{current_year:04d}-{current_month:02d}-01"
        month_end = f"{current_year:04d}-{current_month:02d}-{last_day:02d}"
        ranges.append((month_start, month_end))

        # Move to next month
        current_month += 1
        if current_month > 12:
            current_month = 1
            current_year += 1

    return ranges


@celery.task(bind=True)
def backfill_sequential(
    self,
    start_date: str,
    end_date: str,
    delay_seconds: int = 2,
    skip_existing: bool = False,
    update_recent: bool = True,
):
    """
    Backfill data sequentially, one day at a time.
    Good for small ranges or when you want to monitor progress closely.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        delay_seconds: Delay between days to avoid overwhelming BigQuery
        skip_existing: Skip days that already have data
        update_recent: Update recent stats after backfill completes

    Returns:
        Dict with results for each day
    """
    from pypistats.tasks.pypi import update_recent_stats

    start = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()

    results = {}
    current = start
    total_days = (end - start).days + 1
    processed = 0
    last_successful_date = None

    while current <= end:
        date_str = str(current)
        processed += 1

        # Update task state for monitoring
        self.update_state(
            state="PROGRESS",
            meta={
                "current_date": date_str,
                "processed": processed,
                "total": total_days,
                "percent": int(100 * processed / total_days),
            },
        )

        try:
            if skip_existing:
                # Check if data exists
                from pypistats.tasks.pypi import get_connection_cursor

                conn, cursor = get_connection_cursor()
                cursor.execute("SELECT COUNT(*) FROM overall WHERE date = %s", (date_str,))
                count = cursor.fetchone()[0]
                conn.close()

                if count > 0:
                    print(f"Skipping {date_str} - data already exists ({count} rows)")
                    results[date_str] = {"skipped": True, "existing_rows": count}
                    current += datetime.timedelta(days=1)
                    continue

            print(f"Processing {date_str} ({processed}/{total_days})")
            # For backfill, we don't want to update recent stats during each ETL
            # as it will use wrong date calculations
            result = etl(date_str, purge=False, use_sqlite=True, update_recent=False)
            results[date_str] = result
            last_successful_date = date_str

            # Add delay between days
            if current < end and delay_seconds > 0:
                print(f"Waiting {delay_seconds} seconds before next day...")
                time.sleep(delay_seconds)

        except Exception as e:
            print(f"Error processing {date_str}: {e}")
            results[date_str] = {"error": str(e)}

        current += datetime.timedelta(days=1)

    # Update recent stats based on the last successful date
    if update_recent and last_successful_date:
        print(f"Updating recent stats based on {last_successful_date}...")
        try:
            recent_result = update_recent_stats(last_successful_date)
            results["recent_stats_updated"] = recent_result
            print("Recent stats updated successfully")
        except Exception as e:
            print(f"Error updating recent stats: {e}")
            results["recent_stats_error"] = str(e)

    return results


@celery.task
def backfill_parallel(start_date: str, end_date: str, max_parallel: int = 3, chunk_days: int = 7):
    """
    Backfill data in parallel chunks.
    Good for large ranges when you want faster processing.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        max_parallel: Maximum parallel ETL tasks
        chunk_days: Days per chunk

    Returns:
        Group result that can be monitored
    """
    chunks = get_date_ranges(start_date, end_date, chunk_days)

    print(f"Splitting {start_date} to {end_date} into {len(chunks)} chunks")
    for i, (chunk_start, chunk_end) in enumerate(chunks):
        print(f"  Chunk {i+1}: {chunk_start} to {chunk_end}")

    # Create a group of sequential backfill tasks
    job = group(backfill_sequential.s(chunk_start, chunk_end, delay_seconds=2) for chunk_start, chunk_end in chunks)

    # Apply with limited concurrency
    return job.apply_async(max_retries=3)


@celery.task(bind=True)
def backfill_months(
    self,
    start_month: str,
    end_month: str,
    delay_seconds: int = 2,
    skip_existing: bool = False,
    update_recent: bool = True,
):
    """
    Backfill complete calendar months.

    Args:
        start_month: Start month in YYYY-MM format (e.g., "2024-01")
        end_month: End month in YYYY-MM format (e.g., "2024-12")
        delay_seconds: Delay between days
        skip_existing: Skip days with existing data
        update_recent: Update recent stats after backfill completes

    Returns:
        Dict with results organized by month
    """
    month_ranges = get_month_ranges(start_month, end_month)
    results = {}

    for month_idx, (month_start, month_end) in enumerate(month_ranges):
        month_key = month_start[:7]  # YYYY-MM
        print(f"\nProcessing month {month_key} ({month_idx+1}/{len(month_ranges)})")

        # Update task state
        self.update_state(
            state="PROGRESS",
            meta={
                "current_month": month_key,
                "processed_months": month_idx,
                "total_months": len(month_ranges),
                "percent": int(100 * month_idx / len(month_ranges)),
            },
        )

        # Process the month (don't update recent stats until the end)
        month_results = backfill_sequential(
            month_start,
            month_end,
            delay_seconds=delay_seconds,
            skip_existing=skip_existing,
            update_recent=False,  # Will update at the end of all months
        )

        results[month_key] = month_results

    # Update recent stats based on the last date processed
    if update_recent:
        last_date = month_end
        print(f"Updating recent stats based on {last_date}...")
        try:
            from pypistats.tasks.pypi import update_recent_stats

            recent_result = update_recent_stats(last_date)
            results["recent_stats_updated"] = recent_result
            print("Recent stats updated successfully")
        except Exception as e:
            print(f"Error updating recent stats: {e}")
            results["recent_stats_error"] = str(e)

    return results


@celery.task
def check_backfill_status(start_date: str, end_date: str):
    """
    Check which dates in a range have data.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format

    Returns:
        Dict with status for each date
    """
    from pypistats.tasks.pypi import get_connection_cursor

    start = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()

    conn, cursor = get_connection_cursor()

    # Get all dates with data in the range
    cursor.execute(
        """
        SELECT date, COUNT(*) as row_count, SUM(downloads) as total_downloads
        FROM overall
        WHERE date >= %s AND date <= %s
        GROUP BY date
        ORDER BY date
    """,
        (start_date, end_date),
    )

    existing_data = {row[0]: {"rows": row[1], "downloads": row[2]} for row in cursor.fetchall()}

    conn.close()

    # Build status for all dates
    status = {}
    current = start

    while current <= end:
        date_str = str(current)
        if current in existing_data:
            status[date_str] = {
                "has_data": True,
                "rows": existing_data[current]["rows"],
                "downloads": existing_data[current]["downloads"],
            }
        else:
            status[date_str] = {"has_data": False}

        current += datetime.timedelta(days=1)

    # Summary
    total_days = (end - start).days + 1
    days_with_data = len(existing_data)

    return {
        "summary": {
            "total_days": total_days,
            "days_with_data": days_with_data,
            "days_missing": total_days - days_with_data,
            "percent_complete": round(100 * days_with_data / total_days, 2),
        },
        "dates": status,
    }


# CLI commands for management scripts
def backfill_year(year: int, max_parallel: int = 2):
    """
    Convenience function to backfill an entire year.

    Usage:
        from pypistats.tasks.backfill import backfill_year
        backfill_year(2024)
    """
    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31"

    # Check current status
    print(f"Checking status for year {year}...")
    status = check_backfill_status(start_date, end_date)
    print(f"Status: {status['summary']}")

    if status["summary"]["days_missing"] == 0:
        print(f"Year {year} is complete!")
        return status

    # Start backfill
    print(f"Starting backfill for {status['summary']['days_missing']} missing days...")
    result = backfill_parallel.delay(start_date, end_date, max_parallel=max_parallel, chunk_days=30)

    print(f"Backfill task started: {result.id}")
    return result


def backfill_recent_days(days: int = 7):
    """
    Backfill the most recent N days.

    Usage:
        from pypistats.tasks.backfill import backfill_recent_days
        backfill_recent_days(30)  # Last 30 days
    """
    end_date = datetime.date.today() - datetime.timedelta(days=1)
    start_date = end_date - datetime.timedelta(days=days - 1)

    print(f"Backfilling {days} days: {start_date} to {end_date}")

    result = backfill_sequential.delay(str(start_date), str(end_date), delay_seconds=2, skip_existing=True)

    print(f"Backfill task started: {result.id}")
    return result


if __name__ == "__main__":
    # Example: Backfill January 2024
    # result = backfill_months("2024-01", "2024-01")
    # print(result)

    # Example: Check what's missing in Q1 2024
    status = check_backfill_status("2024-01-01", "2024-03-31")
    print(f"Q1 2024 Status: {status['summary']}")
