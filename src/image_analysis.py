#!/usr/bin/env python3
"""Image analysis functionality using OpenRouter API."""

import base64
import os
import subprocess

import requests

from .config import Config
from .utils import print_flush


def get_video_duration(video_path):
    """Get video duration in seconds using ffprobe."""
    cmd = ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", video_path]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def extract_still_images(video_path, tmpdir):
    """Extract 5 still images from video: beginning, end, and 3 equally spaced."""
    duration = get_video_duration(video_path)

    # Calculate timestamps: beginning (0.5s), end (duration-0.5s), and 3 equally spaced
    timestamps = [
        0.5,  # Beginning
        duration * 0.25,  # 25%
        duration * 0.5,  # 50%
        duration * 0.75,  # 75%
        max(duration - 0.5, 0.5),  # End (but not before 0.5s)
    ]

    image_paths = []
    for i, timestamp in enumerate(timestamps):
        image_path = os.path.join(tmpdir, f"frame_{i:02d}.jpg")
        cmd = ["ffmpeg", "-ss", str(timestamp), "-i", video_path, "-vframes", "1", "-q:v", "5", "-y", image_path]
        subprocess.run(cmd, check=True, capture_output=True)
        image_paths.append(image_path)
        print_flush(f"Extracted frame at {timestamp:.1f}s: {image_path}")

    return image_paths


def encode_image_to_base64(image_path):
    """Encode image to base64 for API transmission."""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def analyze_images_with_openrouter(image_paths):
    """Analyze images using OpenRouter with Gemini model."""
    url = "https://openrouter.ai/api/v1/chat/completions"

    config = Config()
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "X-Title": "Ninadon",
        "HTTP-Referer": "https://github.com/rmoriz/ninadon",
    }

    # Prepare image content for the API
    content = [{"type": "text", "text": Config.IMAGE_ANALYSIS_PROMPT}]

    for image_path in image_paths:
        base64_image = encode_image_to_base64(image_path)
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}})

    data = {"model": Config.ENHANCE_MODEL, "messages": [{"role": "user", "content": content}]}

    import sys

    # Log OpenRouter request (hide API key)
    log_headers = dict(headers)
    if "Authorization" in log_headers:
        log_headers["Authorization"] = "Bearer ***REDACTED***"
    print(f"[OpenRouter IMAGE REQUEST] URL: {url}", file=sys.stderr)
    print(f"[OpenRouter IMAGE REQUEST] Headers: {log_headers}", file=sys.stderr)
    print(f"[OpenRouter IMAGE REQUEST] Model: {Config.ENHANCE_MODEL}", file=sys.stderr)
    print(f"[OpenRouter IMAGE REQUEST] Images: {len(image_paths)}", file=sys.stderr)

    resp = requests.post(url, headers=headers, json=data)
    print(f"[OpenRouter IMAGE RESPONSE] Status: {resp.status_code}", file=sys.stderr)
    print(f"[OpenRouter IMAGE RESPONSE] Body: {resp.text}", file=sys.stderr)

    try:
        resp.raise_for_status()
    except requests.exceptions.HTTPError:
        if resp.status_code == 404:
            print_flush(
                "ERROR: 404 Not Found from OpenRouter API for image analysis. "
                "Please check the ENHANCE_MODEL environment variable."
            )
        raise

    analysis = resp.json()["choices"][0]["message"]["content"]
    return analysis
