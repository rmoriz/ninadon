FROM python:3.13-slim

# Install system dependencies
RUN apt-get update && apt-get install -y ffmpeg procps && rm -rf /var/lib/apt/lists/*

# Set workdir and home
WORKDIR /app
ENV HOME=/app
ENV HF_HOME=/app/.cache
ENV TRANSFORMERS_CACHE=/app/.cache

# Create a non-root user and group with /app as home
RUN groupadd -r appuser && useradd -m -d /app -r -g appuser appuser
RUN chown -R appuser:appuser /app

# Switch to non-root user for all remaining steps
USER appuser
ENV PATH="/app/.local/bin:${PATH}"

# Install faster-whisper and pre-download model as appuser
COPY requirements.txt ./requirements.whisper.txt
RUN grep faster-whisper requirements.whisper.txt > whisper-only.txt
RUN pip install --no-cache-dir -r whisper-only.txt
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('base')"

# Install all other dependencies and app code as appuser
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/

ENTRYPOINT ["python", "src/main.py"]
