# Use Python base image
FROM python:3.13-slim

# Set working directory
WORKDIR /app

# Copy only the required files
COPY main.py .
COPY requirements.txt .

# Install required Python packages
RUN pip install --no-cache-dir ccxt

# Set environment variables (Optional: Override during runtime)
ENV API_KEY=""
ENV API_SECRET=""
ENV STOP_LOSS_PERCENTAGE="0.015"
ENV PROFIT_TARGET_PERCENTAGE="0.005"
ENV PERCENTAGE_OF_BALANCE="0.05"

# Set default command to run the bot
CMD ["python", "main.py"]
