FROM python:3.13-slim

# Add build deps for python packages
# libpq-dev is required to install psycopg2-binary
RUN apt-get update && \
    apt-get install -y libpq-dev && \
    apt-get clean

# Set the working directory to /app
WORKDIR /app

# Create python user to avoid having to run as root
RUN useradd -m python && \
    chown python:python -R /app
# Set the user
USER python

# Set to ensure logs are output promptly
ENV PYTHONUNBUFFERED=1
# Update the path
ENV PATH=/home/python/.local/bin:$PATH

# Add requirements files
ADD requirements.txt .
ADD requirements-dev.txt .

# Install all the dependencies
# Install dev requirements for development environment (formatting tools, etc.)
RUN pip install --user -U pip && \
    pip install --user -r requirements.txt && \
    pip install --user -r requirements-dev.txt

# Add everything
ADD . .

# Set the entrypoint script
ENTRYPOINT ["./docker-entrypoint.sh"]
