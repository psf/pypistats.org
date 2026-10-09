# Backfill Examples for PyPI Stats

## Overview

The backfill system provides several ways to populate historical PyPI download statistics data. This is essential when:
- Setting up a fresh instance
- Recovering from data loss
- Filling gaps in historical data

## Usage Examples

### 1. Check Status of a Date Range

```bash
# Check what data exists for July 2024
docker-compose run --rm celery python manage_backfill.py status 2024-07-01 2024-07-31
```

### 2. Backfill Recent Days

```bash
# Backfill last 7 days (skipping existing data)
docker-compose run --rm celery python manage_backfill.py recent 7

# Or via Python
docker-compose run --rm celery python -c "
from pypistats.tasks.backfill import backfill_recent_days
backfill_recent_days(30)  # Last 30 days
"
```

### 3. Backfill a Specific Date Range (Sequential)

```bash
# Backfill July 2024, one day at a time, with 2-second delay between days
docker-compose run --rm celery python manage_backfill.py sequential \
    2024-07-01 2024-07-31 \
    --delay 2 \
    --skip-existing
```

### 4. Backfill in Parallel (Faster for Large Ranges)

```bash
# Backfill Q3 2024 with 3 parallel workers, 7 days per chunk
docker-compose run --rm celery python manage_backfill.py parallel \
    2024-07-01 2024-09-30 \
    --workers 3 \
    --chunk-days 7
```

### 5. Backfill by Calendar Months

```bash
# Backfill January through June 2024
docker-compose run --rm celery python manage_backfill.py monthly \
    2024-01 2024-06 \
    --delay 2 \
    --skip-existing
```

### 6. Backfill an Entire Year

```bash
# Backfill all of 2024
docker-compose run --rm celery python manage_backfill.py year 2024 --workers 2
```

### 7. Custom Backfill via Python

```python
from pypistats.tasks.backfill import backfill_sequential, check_backfill_status

# Check what's missing
status = check_backfill_status("2024-01-01", "2024-12-31")
print(f"Missing {status['summary']['days_missing']} days in 2024")

# Backfill missing days
if status['summary']['days_missing'] > 0:
    result = backfill_sequential.delay(
        "2024-01-01",
        "2024-12-31", 
        delay_seconds=2,
        skip_existing=True  # Skip days that already have data
    )
    print(f"Backfill task ID: {result.id}")
```

## Monitoring Progress

### Via Celery

```bash
# Monitor active tasks
docker-compose run --rm celery celery -A pypistats.extensions.celery inspect active

# Check task result
docker-compose run --rm celery python -c "
from celery.result import AsyncResult
result = AsyncResult('YOUR_TASK_ID')
print(f'Status: {result.status}')
print(f'Info: {result.info}')
"
```

### Via Flower (if running)

Visit http://localhost:5555 to monitor tasks in the web UI.

## Performance Considerations

1. **BigQuery Rate Limits**: 
   - Use delays between days (2-5 seconds recommended)
   - Don't run too many parallel workers (2-3 max)

2. **Memory Usage**:
   - Current ETL loads all data into memory (~2GB per day)
   - Consider using the optimized SQLite-based ETL for large backfills

3. **Time Estimates**:
   - Each day takes ~2-3 minutes to process
   - 30 days ≈ 60-90 minutes (sequential)
   - 30 days ≈ 20-30 minutes (parallel with 3 workers)

## Recommended Approach for Fresh Instance

For a fresh instance, backfill in stages:

```bash
# 1. Last 7 days (for immediate data)
docker-compose run --rm celery python manage_backfill.py recent 7

# 2. Current month
docker-compose run --rm celery python manage_backfill.py monthly 2024-08 2024-08

# 3. Previous 3 months (parallel)
docker-compose run --rm celery python manage_backfill.py parallel \
    2024-05-01 2024-07-31 \
    --workers 2 \
    --chunk-days 15

# 4. Historical data (monthly batches)
docker-compose run --rm celery python manage_backfill.py monthly \
    2024-01 2024-04 \
    --delay 3 \
    --skip-existing
```

## Database Space Requirements

Approximate storage needs:
- 1 day of data: ~50-100 MB
- 1 month (30 days): ~1.5-3 GB  
- 1 year (365 days): ~20-40 GB

Plan accordingly for your PostgreSQL instance.

## Error Recovery

If a backfill fails:

1. Check which dates completed:
   ```bash
   docker-compose run --rm celery python manage_backfill.py status START_DATE END_DATE
   ```

2. Resume with `--skip-existing` flag:
   ```bash
   docker-compose run --rm celery python manage_backfill.py sequential \
       START_DATE END_DATE \
       --skip-existing
   ```

The system will skip dates that already have data and only process missing days.