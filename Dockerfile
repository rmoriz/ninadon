FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Set workdir
WORKDIR /app

# Set HuggingFace/Whisper cache directory
ENV HF_HOME=/app/.cache
ENV TRANSFORMERS_CACHE=/app/.cache

# --- Install Whisper and pre-download model for optimal caching ---
# Copy minimal requirements for Whisper only
COPY requirements.txt ./requirements.whisper.txt
RUN grep openai-whisper requirements.whisper.txt > whisper-only.txt
RUN pip install --no-cache-dir -r whisper-only.txt
# Pre-download Whisper base model
RUN python -c "import whisper; whisper.load_model('base')"

# --- Install all other dependencies and app code ---
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/

# Create a non-root user and group with home directory
RUN groupadd -r appuser && useradd -m -r -g appuser appuser
RUN chown -R appuser:appuser /home/appuser
ENV HOME=/home/appuser

# Set permissions for /app and cache directories
RUN mkdir -p /app/.cache && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Entrypoint
ENTRYPOINT ["python", "src/main.py"]
