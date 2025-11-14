# Use Python base image
FROM python:3.13-slim

# Set working directory
WORKDIR /app

# Install system dependencies for building Python packages
RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy the application code
COPY bot.py .
COPY binance_client.py .
COPY trading_logic.py .
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Set default command to run the bot
CMD ["python", "bot.py"]
