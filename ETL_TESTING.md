# Testing the ETL Task Locally

## Prerequisites

1. **Google Cloud Service Account**
   - Create a service account in Google Cloud Console
   - Grant it BigQuery Data Viewer permissions
   - Download the JSON key file

2. **Set Environment Variables**
   ```bash
   # Add to your .env file or export directly
   export GOOGLE_SERVICE_ACCOUNT_JSON='<paste your entire service account JSON here>'
   ```

## Method 1: Using the Admin Panel (Easiest)

1. Start the services:
   ```bash
   docker-compose up -d
   ```

2. Access the admin panel:
   ```
   http://localhost:8000/admin
   Username: user
   Password: password
   ```

3. Select a date to backfill and submit the form

## Method 2: Using Celery Directly

1. Start all services:
   ```bash
   docker-compose up -d
   ```

2. Trigger the ETL task manually:
   ```bash
   # Run ETL for yesterday's data (default)
   docker-compose exec celery python -c "from pypistats.tasks.pypi import etl; etl.delay()"
   
   # Run ETL for a specific date
   docker-compose exec celery python -c "from pypistats.tasks.pypi import etl; etl.delay('2025-08-13')"
   ```

3. Monitor the task in Flower:
   ```
   http://localhost:5555
   ```

## Method 3: Using Flask Shell

1. Start services:
   ```bash
   docker-compose up -d
   ```

2. Enter Flask shell:
   ```bash
   docker-compose exec web flask shell
   ```

3. Run the ETL function directly (synchronously):
   ```python
   from pypistats.tasks.pypi import etl_job
   
   # Run for yesterday
   result = etl_job()
   print(result)
   
   # Run for specific date
   result = etl_job('2025-08-13')
   print(result)
   ```

## Method 4: Test Query Only (Without Writing to DB)

1. Create a test script:
   ```bash
   docker-compose exec web python
   ```

2. Test the BigQuery connection:
   ```python
   import os
   from pypistats.tasks.pypi import get_google_credentials, get_query
   from google.cloud import bigquery
   
   # Get credentials
   credentials, project_id = get_google_credentials()
   
   # Create BigQuery client
   client = bigquery.Client(project=project_id, credentials=credentials)
   
   # Test with a simple query
   test_query = """
   SELECT COUNT(*) as total
   FROM `bigquery-public-data.pypi.file_downloads`
   WHERE DATE(timestamp) = '2025-08-13'
   LIMIT 10
   """
   
   # Run query
   query_job = client.query(test_query)
   results = list(query_job.result())
   
   print(f"Query successful! Found {results[0]['total']} downloads")
   ```

## Monitoring & Debugging

### Check Celery Logs
```bash
docker-compose logs -f celery
```

### Check Celery Beat Schedule
```bash
docker-compose logs -f beat
```

### Verify Database Tables
```bash
docker-compose exec postgresql psql -U admin -d pypistats -c "\dt"
```

### Check Recent Downloads
```bash
docker-compose exec postgresql psql -U admin -d pypistats -c "SELECT * FROM overall ORDER BY date DESC LIMIT 10;"
```

## Troubleshooting

### Common Issues

1. **"GOOGLE_SERVICE_ACCOUNT_JSON environment variable is required"**
   - Ensure the environment variable is set in docker-compose.yml or .env file
   - The JSON must be a valid, complete service account key

2. **BigQuery Permission Denied**
   - Verify the service account has BigQuery Data Viewer role
   - Check the project_id in the service account JSON matches your project

3. **Connection to PostgreSQL Failed**
   - Ensure PostgreSQL container is running: `docker-compose ps`
   - Check DATABASE_URL is correctly set

4. **No Data Retrieved**
   - PyPI data may have a 1-2 day delay
   - Try querying for dates 2-3 days in the past

## Running ETL on Schedule

The ETL is configured to run daily at 1 AM UTC via Celery Beat. To verify it's scheduled:

```bash
docker-compose exec beat celery -A pypistats.extensions.celery inspect scheduled
```

## Sample .env File for Local Testing

Create a `.env` file in the project root:

```bash
DATABASE_URL=postgresql://admin:root@localhost:5433/pypistats
REDIS_URL=redis://localhost:6379/0
GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account","project_id":"your-project",...}'
BASIC_AUTH_USER=admin
BASIC_AUTH_PASSWORD=secret
PYPISTATS_SECRET=dev-secret-key
```

Then update docker-compose.yml to use the .env file:
```yaml
x-envs: &envs
  env_file: .env
```