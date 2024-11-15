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

# Copy only the required files
COPY main.py .
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Set environment variables (Optional: Override during runtime)
ENV API_KEY=""
ENV API_SECRET=""
ENV STOP_LOSS_PERCENTAGE="0.015"
ENV PROFIT_TARGET_PERCENTAGE="0.005"
ENV PERCENTAGE_OF_BALANCE="0.05"
ENV TRADING_PAIRS="ADA/USDT,CKB/USDT"
ENV SANDBOX_MODE="True"

# Set default command to run the bot
CMD ["python", "main.py"]
