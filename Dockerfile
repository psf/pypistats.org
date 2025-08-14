# Set variables for reuse
ARG PYTHON_VERSION=3.13-slim-bookworm

# Build stage for dependencies
FROM python:${PYTHON_VERSION} AS build

# Define build arguments
ARG DEVEL=no

# Set Python environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Configure apt to keep cache for Docker BuildKit cache mounts
RUN set -eux; \
    rm -f /etc/apt/apt.conf.d/docker-clean; \
    echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache;

# Install system dependencies with cache mount
# libpq-dev is required for psycopg2-binary compilation
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    set -x \
    && apt-get update \
    && apt-get install --no-install-recommends -y \
        libpq-dev \
        build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Create virtual environment
RUN python3 -m venv /opt/pypistats

# Update PATH to use virtual environment
ENV PATH="/opt/pypistats/bin:${PATH}"

# Upgrade pip, setuptools, and wheel
RUN pip --no-cache-dir --disable-pip-version-check install --upgrade pip setuptools wheel

# Copy only requirements files first (better layer caching)
COPY requirements.txt requirements-dev.txt /tmp/requirements/

# Install dependencies with cache mount
RUN --mount=type=cache,target=/root/.cache/pip \
    set -x \
    && pip --disable-pip-version-check install \
        -r /tmp/requirements/requirements.txt \
        $(if [ "$DEVEL" = "yes" ]; then echo '-r /tmp/requirements/requirements-dev.txt'; fi) \
    && pip check \
    && find /opt/pypistats -name '*.pyc' -delete


# Final production image
FROM python:${PYTHON_VERSION}

# Setup environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app
ENV PATH="/opt/pypistats/bin:${PATH}"

# Define build arguments
ARG DEVEL=no

# Configure apt cache for BuildKit
RUN set -eux; \
    rm -f /etc/apt/apt.conf.d/docker-clean; \
    echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache;

# Install runtime system dependencies
# postgresql-client is useful for database debugging in development
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    set -x \
    && apt-get update \
    && apt-get install --no-install-recommends -y \
        libpq5 \
        $(if [ "$DEVEL" = "yes" ]; then echo 'postgresql-client'; fi) \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Set working directory
WORKDIR /app

# Copy virtual environment from build stage
COPY --from=build /opt/pypistats /opt/pypistats

# Copy application code last to maximize cache efficiency
COPY . /app/

# Pre-compile Python bytecode for faster startup
# This runs our application once to compile all modules
RUN python -c "from pypistats.application import create_app; create_app()" || true

# Set the entrypoint script
ENTRYPOINT ["./docker-entrypoint.sh"]