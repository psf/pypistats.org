#!/usr/bin/env python
"""Management script for backfilling PyPI statistics."""

import argparse
import sys
from datetime import datetime
from datetime import timedelta

from pypistats.tasks.backfill import backfill_months
from pypistats.tasks.backfill import backfill_parallel
from pypistats.tasks.backfill import backfill_recent_days
from pypistats.tasks.backfill import backfill_sequential
from pypistats.tasks.backfill import backfill_year
from pypistats.tasks.backfill import check_backfill_status


def main():
    parser = argparse.ArgumentParser(description="Backfill PyPI statistics data")

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Status command
    status_parser = subparsers.add_parser("status", help="Check backfill status")
    status_parser.add_argument("start_date", help="Start date (YYYY-MM-DD)")
    status_parser.add_argument("end_date", help="End date (YYYY-MM-DD)")

    # Sequential backfill
    seq_parser = subparsers.add_parser("sequential", help="Backfill sequentially")
    seq_parser.add_argument("start_date", help="Start date (YYYY-MM-DD)")
    seq_parser.add_argument("end_date", help="End date (YYYY-MM-DD)")
    seq_parser.add_argument("--delay", type=int, default=2, help="Delay between days (seconds)")
    seq_parser.add_argument("--skip-existing", action="store_true", help="Skip existing data")

    # Parallel backfill
    par_parser = subparsers.add_parser("parallel", help="Backfill in parallel")
    par_parser.add_argument("start_date", help="Start date (YYYY-MM-DD)")
    par_parser.add_argument("end_date", help="End date (YYYY-MM-DD)")
    par_parser.add_argument("--workers", type=int, default=3, help="Max parallel workers")
    par_parser.add_argument("--chunk-days", type=int, default=7, help="Days per chunk")

    # Monthly backfill
    month_parser = subparsers.add_parser("monthly", help="Backfill by calendar months")
    month_parser.add_argument("start_month", help="Start month (YYYY-MM)")
    month_parser.add_argument("end_month", help="End month (YYYY-MM)")
    month_parser.add_argument("--delay", type=int, default=2, help="Delay between days")
    month_parser.add_argument("--skip-existing", action="store_true", help="Skip existing data")

    # Year backfill
    year_parser = subparsers.add_parser("year", help="Backfill entire year")
    year_parser.add_argument("year", type=int, help="Year to backfill")
    year_parser.add_argument("--workers", type=int, default=2, help="Max parallel workers")

    # Recent days backfill
    recent_parser = subparsers.add_parser("recent", help="Backfill recent days")
    recent_parser.add_argument("days", type=int, help="Number of recent days to backfill")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "status":
        result = check_backfill_status(args.start_date, args.end_date)
        print(f"\nBackfill Status for {args.start_date} to {args.end_date}")
        print("=" * 60)
        print(f"Total days: {result['summary']['total_days']}")
        print(f"Days with data: {result['summary']['days_with_data']}")
        print(f"Days missing: {result['summary']['days_missing']}")
        print(f"Percent complete: {result['summary']['percent_complete']}%")

        if result["summary"]["days_missing"] > 0:
            print("\nMissing dates:")
            for date, info in result["dates"].items():
                if not info["has_data"]:
                    print(f"  - {date}")

    elif args.command == "sequential":
        print(f"Starting sequential backfill: {args.start_date} to {args.end_date}")
        print(f"Delay: {args.delay}s, Skip existing: {args.skip_existing}")

        result = backfill_sequential.delay(
            args.start_date, args.end_date, delay_seconds=args.delay, skip_existing=args.skip_existing
        )
        print(f"Task started with ID: {result.id}")
        print(f"Monitor progress with: celery -A pypistats.extensions.celery inspect active")

    elif args.command == "parallel":
        print(f"Starting parallel backfill: {args.start_date} to {args.end_date}")
        print(f"Workers: {args.workers}, Chunk days: {args.chunk_days}")

        result = backfill_parallel.delay(
            args.start_date, args.end_date, max_parallel=args.workers, chunk_days=args.chunk_days
        )
        print(f"Task group started with ID: {result.id}")

    elif args.command == "monthly":
        print(f"Starting monthly backfill: {args.start_month} to {args.end_month}")
        print(f"Delay: {args.delay}s, Skip existing: {args.skip_existing}")

        result = backfill_months.delay(
            args.start_month, args.end_month, delay_seconds=args.delay, skip_existing=args.skip_existing
        )
        print(f"Task started with ID: {result.id}")

    elif args.command == "year":
        print(f"Starting year backfill for {args.year}")
        result = backfill_year(args.year, max_parallel=args.workers)

    elif args.command == "recent":
        print(f"Starting backfill for last {args.days} days")
        result = backfill_recent_days(args.days)


if __name__ == "__main__":
    main()
