FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Set workdir
WORKDIR /app

# Set HuggingFace/Whisper cache directory
ENV HF_HOME=/app/.cache
ENV TRANSFORMERS_CACHE=/app/.cache

# Create a non-root user and group with home directory
RUN groupadd -r appuser && useradd -m -r -g appuser appuser
RUN chown -R appuser:appuser /home/appuser
RUN mkdir -p /app/.cache && chown -R appuser:appuser /app
ENV HOME=/home/appuser

# Switch to non-root user for pip install and model download
USER appuser

# Install Whisper and pre-download model as appuser
COPY requirements.txt ./requirements.whisper.txt
RUN grep openai-whisper requirements.whisper.txt > whisper-only.txt
RUN pip install --no-cache-dir -r whisper-only.txt
RUN python -c "import whisper; whisper.load_model('base')"

# Switch back to root for remaining steps
USER root

# Install all other dependencies and app code as root
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/

# Switch to appuser for runtime
USER appuser

ENTRYPOINT ["python", "src/main.py"]
