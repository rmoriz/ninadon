#!/usr/bin/env python3
"""Audio transcription functionality using Whisper and platform APIs."""

import os
import re
import subprocess
from pathlib import Path

import whisper
import yt_dlp

from .config import Config
from .utils import print_flush


def get_whisper_model_directory():
    """Get the Whisper model directory from environment variable or default."""
    return Config.get_whisper_model_directory()


def download_whisper_model(model_name="base"):
    """Download and cache a Whisper model to the specified directory."""
    model_dir = get_whisper_model_directory()
    model_dir.mkdir(parents=True, exist_ok=True)

    print_flush(f"Downloading Whisper model '{model_name}' to {model_dir}")

    # Set the cache directory for whisper
    cache_dir = model_dir / ".cache"
    cache_dir.mkdir(exist_ok=True)

    # Temporarily set environment variables for whisper to use our cache
    original_cache = os.environ.get("XDG_CACHE_HOME")
    os.environ["XDG_CACHE_HOME"] = str(cache_dir)

    try:
        # Load the model, which will download it to our cache directory
        model = whisper.load_model(model_name, download_root=str(model_dir))
        print_flush(f"Successfully downloaded and cached Whisper model '{model_name}'")
        return model
    except Exception as e:
        print_flush(f"Error downloading Whisper model '{model_name}': {e}")
        raise
    finally:
        # Restore original environment
        if original_cache:
            os.environ["XDG_CACHE_HOME"] = original_cache
        elif "XDG_CACHE_HOME" in os.environ:
            del os.environ["XDG_CACHE_HOME"]


def get_whisper_model(model_name="base"):
    """Get a Whisper model, downloading it if not already cached."""
    model_dir = get_whisper_model_directory()

    # Check if model is already downloaded
    try:
        # Try to load from our cache directory
        cache_dir = model_dir / ".cache"
        original_cache = os.environ.get("XDG_CACHE_HOME")
        os.environ["XDG_CACHE_HOME"] = str(cache_dir)

        model = whisper.load_model(model_name, download_root=str(model_dir))
        print_flush(f"Loaded cached Whisper model '{model_name}' from {model_dir}")

        # Restore original environment
        if original_cache:
            os.environ["XDG_CACHE_HOME"] = original_cache
        elif "XDG_CACHE_HOME" in os.environ:
            del os.environ["XDG_CACHE_HOME"]

        return model
    except Exception:
        # Model not found or corrupted, download it
        print_flush(f"Whisper model '{model_name}' not found in cache, downloading...")
        return download_whisper_model(model_name)


def transcribe_video(video_path):
    """Transcribe video using Whisper."""
    # Verify file exists and is readable
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")

    # Check if the video has an audio stream
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_name",
                "-print_format",
                "csv=p=0",
                video_path,
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        audio_codec = result.stdout.strip()
        if not audio_codec:
            print_flush("Warning: Video file has no audio stream. Cannot transcribe.")
            return ""

    except subprocess.CalledProcessError:
        print_flush("Warning: Could not detect audio stream. Attempting transcription anyway...")

    try:
        model = get_whisper_model(Config.WHISPER_MODEL)
        result = model.transcribe(video_path)
        return result["text"]
    except Exception as e:
        error_msg = str(e)
        if "Failed to load audio" in error_msg and "does not contain any stream" in error_msg:
            print_flush("Error: Video file contains no audio stream. Cannot transcribe.")
            return ""
        else:
            # Re-raise other errors
            raise


def parse_subtitle_file(subtitle_path):
    """
    Parse a subtitle file and extract the text content.
    Supports VTT, SRT, and other common subtitle formats.
    """
    try:
        with open(subtitle_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Remove WebVTT headers and timing information
        lines = content.split("\n")
        text_lines = []

        for line in lines:
            line = line.strip()
            # Skip empty lines, timing lines, and WebVTT/SRT formatting
            if (
                line
                and not line.startswith("WEBVTT")
                and not line.startswith("NOTE")
                and "-->" not in line
                and not line.isdigit()
                and not line.startswith("STYLE")
                and not line.startswith("::cue")
            ):
                # Remove any remaining HTML/XML tags
                clean_line = re.sub(r"<[^>]+>", "", line)
                if clean_line.strip():
                    text_lines.append(clean_line.strip())

        return " ".join(text_lines)

    except Exception as e:
        print_flush(f"Error parsing subtitle file {subtitle_path}: {e}")
        return ""


def extract_transcript_from_platform(url, tmpdir):
    """
    Try to extract transcript/subtitles from the platform using yt-dlp.
    Returns the transcript text if available, None otherwise.
    """
    print_flush("Checking for platform-provided transcripts...")

    # Configure yt-dlp to extract subtitles
    subtitle_dir = os.path.join(tmpdir, "subtitles")
    os.makedirs(subtitle_dir, exist_ok=True)

    ydl_opts = {
        "writesubtitles": True,  # Extract manual subtitles
        "writeautomaticsub": True,  # Extract automatic captions
        "skip_download": True,  # Don't download video, just subtitles
        "subtitleslangs": ["en", "en-US", "en-GB"],  # Prefer English
        "outtmpl": os.path.join(subtitle_dir, "%(title)s.%(ext)s"),
        "quiet": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # type: ignore
            info = ydl.extract_info(url, download=True)

            # Check if subtitles were downloaded
            if info and ("subtitles" in info or "automatic_captions" in info):
                # Look for downloaded subtitle files
                for file in os.listdir(subtitle_dir):
                    if file.endswith((".vtt", ".srt", ".ass", ".ttml")):
                        subtitle_path = os.path.join(subtitle_dir, file)
                        print_flush(f"Found platform transcript: {subtitle_path}")

                        # Read and parse the subtitle file
                        transcript = parse_subtitle_file(subtitle_path)
                        if transcript.strip():
                            print_flush("Successfully extracted transcript from platform")
                            return transcript

            print_flush("No platform transcripts found or extracted")
            return None

    except Exception as e:
        print_flush(f"Failed to extract platform transcript: {e}")
        return None
