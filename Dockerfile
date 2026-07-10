FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies needed for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port (Railway sets $PORT dynamically)
EXPOSE 8000

# Use shell script to run migrations and start server
CMD ["bash", "start.sh"]
