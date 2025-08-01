FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Set workdir
WORKDIR /app

# Copy requirements and source
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/

# Entrypoint
ENTRYPOINT ["python", "src/main.py"]
