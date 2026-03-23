# Base image with a stable Python runtime for Flask.
FROM python:3.11-slim

WORKDIR /app

# Avoid .pyc files and force direct logs to stdout/stderr inside the container.
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Build dependencies required by psycopg2 and PostgreSQL client headers.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies before copying the full source tree for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application source used by the web service container.
COPY . .
