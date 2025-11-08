FROM python:3.11-slim

# Always keep output clean (no .pyc etc.)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system essentials (for redis-py, aiogram etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy & install python dependencies first for Docker cache efficiency
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy the rest of the app
COPY . .

# Create log folder (persistent through volume if needed)
RUN mkdir -p /app/logs && touch /app/logs/bot.log

# Default command
CMD ["python", "main.py"]
