# PyPIStats Admin Features

## Overview
The admin panel in PyPIStats is a simple, focused interface designed primarily for ETL management and data backfilling. It's protected by HTTP Basic Authentication.

## Access
- **URL**: http://localhost:8000/admin
- **Default Credentials**: 
  - Username: `user`
  - Password: `password`
- **Authentication**: HTTP Basic Auth (browser popup)

## Features

### 1. Manual ETL Trigger (Primary Feature)
The admin panel provides a single, essential function:

**Date-Specific Data Backfill**
- Select any date using the date picker
- Submit to trigger an ETL job for that specific date
- The system will:
  1. Query BigQuery for PyPI download data for the selected date
  2. Process and aggregate the data by:
     - Package
     - Python version (major and minor)
     - Operating system
     - With/without mirrors
  3. Store results in PostgreSQL
  4. Update recent statistics (day/week/month)
  5. Clean up old data (>180 days)

### Use Cases
1. **Backfilling Missing Data**: If the scheduled ETL failed for certain dates
2. **Historical Data Import**: Loading data for past dates when setting up
3. **Data Correction**: Re-running ETL for a date if there were issues
4. **Testing**: Manually triggering ETL for specific dates during development

## How It Works

When you submit a date:
1. The form triggers `etl.apply_async(args=(str(date),))` via Celery
2. The task runs asynchronously in the background
3. You'll see confirmation: "{date} submitted"
4. Monitor progress via:
   - Celery logs: `docker-compose logs -f celery`
   - Flower dashboard: http://localhost:5555

## Scheduled ETL
Note: The system also runs ETL automatically:
- **Schedule**: Daily at 1 AM UTC
- **Target**: Previous day's data
- **Managed by**: Celery Beat

## Security Considerations
- Basic Auth credentials are set via environment variables
- Should use HTTPS in production (handled by reverse proxy)
- Consider using stronger authentication for production deployments

## Limitations
- No user management interface (single shared admin account)
- No ETL job status tracking in the UI (check logs/Flower)
- No ability to cancel running jobs from the UI
- No data visualization or statistics in admin panel

## Related Tools
For more admin capabilities, use:
- **Flower** (http://localhost:5555): Monitor Celery tasks
- **Database queries**: Direct PostgreSQL access for data inspection
- **API endpoints**: Public API for viewing statistics at /api/