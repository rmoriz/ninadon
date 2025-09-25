FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y ffmpeg procps curl unzip && rm -rf /var/lib/apt/lists/*

# Install Deno (required for future yt-dlp versions)
RUN curl -fsSL https://deno.land/install.sh | sh
RUN mv /root/.deno/bin/deno /usr/local/bin/deno

# Set workdir and home
WORKDIR /app
ENV HOME=/app

# Create data directory for persistent storage
RUN mkdir -p /app/data

# Create a non-root user and group with /app as home
RUN groupadd -r appuser && useradd -m -d /app -r -g appuser appuser
RUN chown -R appuser:appuser /app

# Switch to non-root user for all remaining steps
USER appuser
ENV PATH="/app/.local/bin:${PATH}"

# Install dependencies and app code as appuser
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/

ENTRYPOINT ["python", "-m", "src.main"]
