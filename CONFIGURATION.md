# PyPIStats.org Configuration Requirements

## Environment Variables

### Required Environment Variables

#### Database Configuration (PostgreSQL)
- `DATABASE_URL` - PostgreSQL connection URL (e.g., `postgresql://user:password@host:5432/dbname`)

#### Redis Configuration
- `REDIS_URL` - Redis connection URL (e.g., `redis://redis:6379/0`)

#### Google BigQuery Configuration
- `GOOGLE_SERVICE_ACCOUNT_JSON` - Complete Google service account JSON (as a string)

#### Authentication & Security
- `BASIC_AUTH_USER` - Username for admin panel basic authentication
- `BASIC_AUTH_PASSWORD` - Password for admin panel basic authentication
- `GITHUB_CLIENT_ID` - GitHub OAuth application client ID (optional, for user authentication)
- `GITHUB_CLIENT_SECRET` - GitHub OAuth application client secret (optional, for user authentication)
- `PYPISTATS_SECRET` - Flask secret key for session encryption (defaults to `"secret-key"` if not set)

### Optional Environment Variables

#### Application Configuration
- `ENV` - Environment name (`development`, `production`, `test`, `local`) - defaults to `development`
- `FLASK_APP` - Flask application entry point (should be `pypistats/run.py`)
- `FLASK_ENV` - Flask environment (`development` or `production`)
- `FLASK_DEBUG` - Enable Flask debug mode (`1` for true, `0` for false)

#### Deployment Configuration
- `PORT` - Port for web server to bind to (defaults to `5000`)
- `BIND_UNIX_SOCKET` - If set, bind to Unix socket at `/var/run/cabotage/cabotage.sock` instead of TCP port
- `WEB_CONCURRENCY` - Number of Gunicorn worker processes (defaults to `2`)
- `LOG_LEVEL` - Application log level (`debug`, `info`, `warning`, `error`) - defaults to `info`

## Configuration Files

### Flask Application (`pypistats/config.py`)
The application uses different configuration classes based on the `ENV` variable:
- `development` - DevConfig (DEBUG=True)
- `production` - ProdConfig (DEBUG=False)
- `local` - LocalConfig (DEBUG=True)
- `test` - TestConfig (DEBUG=True, TESTING=True)

### Gunicorn (`gunicorn.conf.py`)
Web server configuration that uses:
- `PORT` environment variable for binding
- `WEB_CONCURRENCY` for worker count
- `LOG_LEVEL` for logging verbosity

### Docker Compose (`docker-compose.yml`)
Provides default values for local development:
- PostgreSQL: `admin`/`root` on port 5433
- Redis: port 6379
- Basic Auth: `user`/`password`

## Services Required

1. **PostgreSQL 16+** - Primary database for storing aggregated statistics
2. **Redis 7+** - Message broker for Celery background tasks
3. **Google BigQuery Access** - For querying PyPI public download data
   - Requires a service account with BigQuery Data Viewer permissions
   - The service account JSON includes the project ID automatically

## Background Tasks

### Celery Configuration
- **Worker**: Processes ETL tasks for importing BigQuery data
- **Beat**: Schedules daily ETL at 1 AM UTC
- **Flower**: Optional monitoring dashboard on port 5555

### ETL Schedule
The application runs a daily ETL job at 1 AM UTC that:
1. Queries Google BigQuery for PyPI download statistics
2. Aggregates data by package, version, Python version, and system
3. Stores results in PostgreSQL
4. Maintains a 180-day retention period

## Deployment Checklist

### Minimum Required Setup
```bash
# Database
export DATABASE_URL=postgresql://user:password@host:5432/pypistats

# Redis
export REDIS_URL=redis://redis_host:6379/0

# Google BigQuery (service account JSON as a single string)
export GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account","project_id":"your-project","private_key_id":"...","private_key":"-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n","client_email":"...@....iam.gserviceaccount.com","client_id":"...","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token","auth_provider_x509_cert_url":"https://www.googleapis.com/oauth2/v1/certs","client_x509_cert_url":"..."}'

# Security
export BASIC_AUTH_USER=admin
export BASIC_AUTH_PASSWORD=secure_password_here
export PYPISTATS_SECRET=your_secret_key_here

# Application
export ENV=production
export PORT=8000
```

### Optional GitHub OAuth Setup
If you want to enable GitHub authentication for users:
```bash
export GITHUB_CLIENT_ID=your_github_oauth_app_id
export GITHUB_CLIENT_SECRET=your_github_oauth_app_secret
```

## Notes

- All PostgreSQL connection parameters are required for the application to start
- Google BigQuery credentials are required for the ETL tasks to function
- The `PYPISTATS_SECRET` should be a long, random string in production
- Basic auth credentials protect the `/admin` endpoint for manual ETL triggers
- The application expects to run behind a proxy that sets `X-Forwarded-Proto` header for HTTPS redirect