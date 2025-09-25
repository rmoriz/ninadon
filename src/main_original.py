#!/usr/bin/env python3
import warnings

warnings.filterwarnings(
    "ignore", message="FP16 is not supported on CPU; using FP32 instead"
)
import argparse
import base64
import json
import mimetypes
import os
import re
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests
import whisper
import yt_dlp
from flask import Flask, jsonify, request
from flask_httpauth import HTTPBasicAuth
from mastodon import Mastodon


def print_flush(*args, **kwargs):
    import builtins

    builtins.print(*args, **kwargs)
    import sys

    sys.stdout.flush()


def get_whisper_model_directory():
    """Get the Whisper model directory from environment variable or default."""
    default_dir = os.path.expanduser("~/.ninadon/whisper")
    model_dir = os.environ.get("WHISPER_MODEL_DIRECTORY", default_dir)
    return Path(model_dir)


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


def run_ydl(url, ydl_opts, download):
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=download)
        return info, ydl


def collect_formats(formats):
    muxed, videos, audios = [], [], []
    for f in formats:
        if not f.get("url"):
            continue
        size = f.get("filesize") or f.get("filesize_approx")
        if not size:
            continue
        if f.get("vcodec") != "none" and f.get("acodec") != "none":
            muxed.append((size, f))
        elif f.get("vcodec") != "none":
            videos.append((size, f))
        elif f.get("acodec") != "none":
            audios.append((size, f))
    return muxed, videos, audios


def build_candidates(muxed, videos, audios):
    candidates = [(size, f["format_id"]) for size, f in muxed]
    for vsize, v in videos:
        for asize, a in audios:
            total = vsize + asize
            candidates.append((total, f"{v['format_id']}+{a['format_id']}"))
    return candidates


def select_filepath(info, ydl):
    if "requested_downloads" in info:
        return info["requested_downloads"][0]["filepath"]
    else:
        return ydl.prepare_filename(info)


def fix_downloaded_filepath(filepath, tmpdir):
    """
    Fix problematic file paths after download, especially .NA extensions
    """
    # Check if the file exists as-is
    if filepath and os.path.exists(filepath):
        return filepath

    # If filepath is None or file doesn't exist, search for any video file in tmpdir
    if not filepath or not os.path.exists(filepath):
        print_flush(f"File not found at expected path: {filepath}")
        print_flush("Searching for downloaded video files...")

        # Search for any video files in the directory
        for file in os.listdir(tmpdir):
            file_path = os.path.join(tmpdir, file)
            if os.path.isfile(file_path) and file.startswith("video"):
                print_flush(f"Found video file: {file_path}")
                filepath = file_path
                break

        if not filepath or not os.path.exists(filepath):
            raise FileNotFoundError(f"No video file found in {tmpdir}")

    # Handle .NA extension specifically
    if filepath.endswith(".NA"):
        print_flush(f"Handling .NA extension for file: {filepath}")

        # Try to detect the actual format and rename
        try:
            # Use ffprobe to detect the format
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "quiet",
                    "-print_format",
                    "json",
                    "-show_format",
                    filepath,
                ],
                capture_output=True,
                text=True,
                check=True,
            )

            format_info = json.loads(result.stdout)
            format_name = format_info.get("format", {}).get("format_name", "")

            # Determine appropriate extension
            if "mp4" in format_name or "mov" in format_name:
                new_ext = ".mp4"
            elif "webm" in format_name:
                new_ext = ".webm"
            elif "mkv" in format_name:
                new_ext = ".mkv"
            else:
                new_ext = ".mp4"  # Default fallback

            new_path = filepath.replace(".NA", new_ext)
            os.rename(filepath, new_path)
            filepath = new_path
            print_flush(f"Renamed {filepath.replace(new_ext, '.NA')} to {filepath}")

        except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as e:
            print_flush(f"Warning: Could not detect video format: {e}")
            # Try renaming to .mp4 as fallback
            new_path = filepath.replace(".NA", ".mp4")
            try:
                os.rename(filepath, new_path)
                filepath = new_path
                print_flush(f"Fallback: renamed to {filepath}")
            except OSError as rename_error:
                print_flush(f"Error renaming file: {rename_error}")
                # If renaming fails, just use the original path
                pass

    return filepath


def download_video(url, tmpdir):
    outtmpl = os.path.join(tmpdir, "video.%(ext)s")
    ydl_opts_info = {"quiet": True}
    info, _ydl = run_ydl(url, ydl_opts_info, False)
    formats = info.get("formats", []) if info else []
    muxed, videos, audios = collect_formats(formats)
    candidates = build_candidates(muxed, videos, audios)
    under_30mb = [c for c in candidates if c[0] < 30 * 1024 * 1024]

    filepath = None

    if under_30mb:
        best_candidate = under_30mb[-1]
        chosen_size, chosen_format_id = best_candidate[0], best_candidate[1]
        print_flush(
            f"Selected format {chosen_format_id} with size {chosen_size // (1024 * 1024)} MB"
        )
        ydl_opts = {
            "outtmpl": outtmpl,
            "format": chosen_format_id,
            "merge_output_format": "mp4",
            "quiet": True,
        }
        try:
            info, ydl = run_ydl(url, ydl_opts, True)
            filepath = select_filepath(info, ydl)
        except Exception as e:
            print_flush(
                f"Error downloading selected format: {e}\nFalling back to 'best' format."
            )
            filepath = None

    if not filepath:
        print_flush("No directly downloadable formats found! Available formats:")
        if formats:
            for f in formats:
                print_flush(
                    f"format_id={f.get('format_id')}, vcodec={f.get('vcodec')}, acodec={f.get('acodec')}, filesize={f.get('filesize')}, url={'yes' if f.get('url') else 'no'}"
                )
        else:
            print_flush("No formats available")
        print_flush("Falling back to 'best' format.")
        ydl_opts = {
            "outtmpl": os.path.join(tmpdir, "video.%(ext)s"),
            "format": "best",
            "merge_output_format": "mp4",
            "quiet": True,
        }
        info, ydl = run_ydl(url, ydl_opts, True)
        filepath = select_filepath(info, ydl)

    # Handle problematic file extensions after download
    if filepath and (filepath.endswith(".NA") or not os.path.exists(filepath)):
        filepath = fix_downloaded_filepath(filepath, tmpdir)

    # Ensure we have valid info
    if not info:
        raise RuntimeError("Failed to extract video information")

    title = info.get("title", "")
    description = info.get("description", "")
    uploader = info.get("uploader", info.get("channel", info.get("author", "")))

    # Extract hashtags from title and description
    hashtags = []
    text_to_search = f"{title} {description}"
    hashtag_matches = re.findall(r"#\w+", text_to_search)
    hashtags = list(set(hashtag_matches))  # Remove duplicates

    # Determine platform from URL
    platform = "unknown"
    if "tiktok.com" in url.lower():
        platform = "tiktok"
    elif "youtube.com" in url.lower() or "youtu.be" in url.lower():
        platform = "youtube"
    elif "instagram.com" in url.lower():
        platform = "instagram"

    mime_type = None
    if "requested_downloads" in info and info["requested_downloads"]:
        mime_type = info["requested_downloads"][0].get("mime_type")
    if not mime_type:
        mime_type = info.get("mime_type")

    return filepath, title, description, uploader, hashtags, platform, mime_type


def transcribe_video(video_path):
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
        print_flush(
            "Warning: Could not detect audio stream. Attempting transcription anyway..."
        )

    try:
        default_model = os.environ.get("WHISPER_MODEL", "base")
        model = get_whisper_model(default_model)
        result = model.transcribe(video_path)
        return result["text"]
    except Exception as e:
        error_msg = str(e)
        if (
            "Failed to load audio" in error_msg
            and "does not contain any stream" in error_msg
        ):
            print_flush(
                "Error: Video file contains no audio stream. Cannot transcribe."
            )
            return ""
        else:
            # Re-raise other errors
            raise


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
                            print_flush(
                                "Successfully extracted transcript from platform"
                            )
                            return transcript

            print_flush("No platform transcripts found or extracted")
            return None

    except Exception as e:
        print_flush(f"Failed to extract platform transcript: {e}")
        return None


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


def get_video_duration(video_path):
    """Get video duration in seconds using ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-show_entries",
        "format=duration",
        "-of",
        "csv=p=0",
        video_path,
    ]
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
        cmd = [
            "ffmpeg",
            "-ss",
            str(timestamp),
            "-i",
            video_path,
            "-vframes",
            "1",
            "-q:v",
            "5",
            "-y",
            image_path,
        ]
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
    api_key = getenv("OPENROUTER_API_KEY", required=True)
    model = getenv("ENHANCE_MODEL", "google/gemini-2.5-flash-lite")
    url = "https://openrouter.ai/api/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "Ninadon",
        "HTTP-Referer": "https://github.com/rmoriz/ninadon",
    }

    # Prepare image content for the API
    image_prompt = getenv(
        "IMAGE_ANALYSIS_PROMPT",
        "Analyze these photos from a tiktok clip, make a connection between the photos",
    )
    content = [{"type": "text", "text": image_prompt}]

    for image_path in image_paths:
        base64_image = encode_image_to_base64(image_path)
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
            }
        )

    data = {"model": model, "messages": [{"role": "user", "content": content}]}

    import sys

    # Log OpenRouter request (hide API key)
    log_headers = dict(headers)
    if "Authorization" in log_headers:
        log_headers["Authorization"] = "Bearer ***REDACTED***"
    print(f"[OpenRouter IMAGE REQUEST] URL: {url}", file=sys.stderr)
    print(f"[OpenRouter IMAGE REQUEST] Headers: {log_headers}", file=sys.stderr)
    print(f"[OpenRouter IMAGE REQUEST] Model: {model}", file=sys.stderr)
    print(f"[OpenRouter IMAGE REQUEST] Images: {len(image_paths)}", file=sys.stderr)

    resp = requests.post(url, headers=headers, json=data)
    print(f"[OpenRouter IMAGE RESPONSE] Status: {resp.status_code}", file=sys.stderr)
    print(f"[OpenRouter IMAGE RESPONSE] Body: {resp.text}", file=sys.stderr)

    try:
        resp.raise_for_status()
    except requests.exceptions.HTTPError:
        if resp.status_code == 404:
            print_flush(
                "ERROR: 404 Not Found from OpenRouter API for image analysis. This may mean the model name is invalid or unavailable. Please check the ENHANCE_MODEL environment variable."
            )
        raise

    analysis = resp.json()["choices"][0]["message"]["content"]
    return analysis


def getenv(key, default=None, required=False):
    val = os.environ.get(key, default)
    if required and not val:
        raise RuntimeError(f"{key} environment variable not set")
    return val


def get_data_root():
    """Get the root data directory from environment variable or default."""
    data_path = os.environ.get("DATA_PATH", "/app/data")
    os.makedirs(data_path, exist_ok=True)
    return data_path


def get_database_path(uploader):
    """Get the database file path for a specific user."""
    # Create user directory if it doesn't exist
    data_root = get_data_root()
    user_dir = os.path.join(data_root, uploader)
    os.makedirs(user_dir, exist_ok=True)
    return os.path.join(user_dir, "database.json")


def get_context_path(uploader):
    """Get the context file path for a specific user."""
    data_root = get_data_root()
    user_dir = os.path.join(data_root, uploader)
    os.makedirs(user_dir, exist_ok=True)
    return os.path.join(user_dir, "context.json")


def load_database(uploader):
    """Load the database for a specific user."""
    db_path = get_database_path(uploader)
    if os.path.exists(db_path):
        try:
            with open(db_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print_flush(f"Warning: Could not load database for {uploader}: {e}")
            return []
    return []


def save_database(uploader, database):
    """Save the database for a specific user, keeping only the latest 25 entries."""
    # Keep only the latest 25 entries
    if len(database) > 25:
        database = database[-25:]

    db_path = get_database_path(uploader)
    try:
        with open(db_path, "w", encoding="utf-8") as f:
            json.dump(database, f, indent=2, ensure_ascii=False)
        print_flush(f"Database saved for {uploader}: {len(database)} entries")
    except IOError as e:
        print_flush(f"Warning: Could not save database for {uploader}: {e}")


def add_to_database(
    uploader, title, description, hashtags, platform, transcript, image_analysis=None
):
    """Add a new entry to the user's database or update existing entry if video already exists."""
    database = load_database(uploader)

    # Check if entry with same title already exists
    existing_index = None
    for i, entry in enumerate(database):
        if entry.get("title") == title and entry.get("platform") == platform:
            existing_index = i
            break

    # Create new entry data
    entry_data = {
        "date": datetime.now().isoformat(),
        "title": title,
        "description": description,
        "hashtags": hashtags,
        "platform": platform,
        "transcript": transcript,
    }

    if image_analysis:
        entry_data["image_recognition"] = image_analysis

    if existing_index is not None:
        # Update existing entry
        print_flush(f"Updating existing database entry for: {title}")
        database[existing_index] = entry_data
    else:
        # Add new entry
        print_flush(f"Adding new database entry for: {title}")
        database.append(entry_data)

    save_database(uploader, database)
    return database


def generate_context_summary(uploader):
    """Generate a context summary from the user's database using OpenRouter."""
    database = load_database(uploader)

    if not database:
        print_flush(
            f"No database entries found for {uploader}, skipping context generation"
        )
        return None

    # Load existing context to build upon it
    existing_context = load_context(uploader)

    # Prepare the database content for summarization
    db_content = "Recent video history:\n\n"
    for i, entry in enumerate(database[-10:], 1):  # Use last 10 entries for context
        db_content += f"Video {i}:\n"
        db_content += f"Date: {entry['date']}\n"
        db_content += f"Platform: {entry['platform']}\n"
        db_content += f"Title: {entry['title']}\n"
        db_content += f"Description: {entry['description']}\n"
        db_content += f"Hashtags: {', '.join(entry['hashtags'])}\n"
        db_content += (
            f"Transcript: {entry['transcript'][:500]}...\n"  # Limit transcript length
        )
        if entry.get("image_recognition"):
            db_content += f"Image Recognition: {entry['image_recognition'][:300]}...\n"
        db_content += "\n---\n\n"

    # Include existing context if available
    if existing_context:
        db_content += f"Previous context summary:\n{existing_context}\n\n---\n\n"

    # Call OpenRouter to summarize the context
    api_key = getenv("OPENROUTER_API_KEY", required=True)
    context_model = getenv("CONTEXT_MODEL", "tngtech/deepseek-r1t2-chimera:free")
    url = "https://openrouter.ai/api/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "Ninadon",
        "HTTP-Referer": "https://github.com/rmoriz/ninadon",
    }

    system_prompt = getenv(
        "CONTEXT_PROMPT",
        "Analyze the following video history and create a concise context summary that captures the user's content themes, interests, and patterns. Focus on recurring topics, style, and audience. If a previous context summary is provided, build upon it and update it with new insights from the recent videos, maintaining continuity while incorporating new patterns or changes.",
    )

    data = {
        "model": context_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": db_content},
        ],
    }

    import sys

    print(f"[OpenRouter CONTEXT REQUEST] URL: {url}", file=sys.stderr)
    print(f"[OpenRouter CONTEXT REQUEST] Model: {context_model}", file=sys.stderr)
    print(
        f"[OpenRouter CONTEXT REQUEST] Database entries: {len(database)}",
        file=sys.stderr,
    )
    print(
        f"[OpenRouter CONTEXT REQUEST] Existing context: {'Yes' if existing_context else 'No'}",
        file=sys.stderr,
    )

    try:
        resp = requests.post(url, headers=headers, json=data)
        print(
            f"[OpenRouter CONTEXT RESPONSE] Status: {resp.status_code}", file=sys.stderr
        )

        resp.raise_for_status()
        context_summary = resp.json()["choices"][0]["message"]["content"]

        # Save the context summary
        context_path = get_context_path(uploader)
        context_data = {
            "generated_at": datetime.now().isoformat(),
            "summary": context_summary,
            "based_on_entries": len(database),
        }

        with open(context_path, "w", encoding="utf-8") as f:
            json.dump(context_data, f, indent=2, ensure_ascii=False)

        print_flush(f"Context summary generated and saved for {uploader}")
        return context_summary

    except requests.exceptions.HTTPError as e:
        print_flush(f"Warning: Context generation failed: {e}")
        return None
    except Exception as e:
        print_flush(f"Warning: Could not generate context: {e}")
        return None


def load_context(uploader):
    """Load the context summary for a specific user."""
    context_path = get_context_path(uploader)
    if os.path.exists(context_path):
        try:
            with open(context_path, "r", encoding="utf-8") as f:
                context_data = json.load(f)
                return context_data.get("summary", "")
        except (json.JSONDecodeError, IOError) as e:
            print_flush(f"Warning: Could not load context for {uploader}: {e}")
    return None


def summarize_text(
    transcript, description, uploader, image_analysis=None, context=None
):
    system_prompt = getenv(
        "SYSTEM_PROMPT",
        'Summarize the following video transcript, description, and account name. Additionally, create a detailed video description for visually impaired people (up to 1400 characters) that describes what happens in the video based on the transcript and any available visual information. Respond with valid JSON in this exact format: {"summary": "your summary here", "video_description": "detailed description for visually impaired up to 1400 characters"}',
    )
    api_key = getenv("OPENROUTER_API_KEY", required=True)
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "Ninadon",
        "HTTP-Referer": "https://github.com/rmoriz/ninadon",
    }
    user_prompt = getenv("USER_PROMPT", "")
    merged_transcript = f"{user_prompt}\n\n{transcript}" if user_prompt else transcript

    user_content = f"Account name: {uploader}\nDescription: {description}\nTranscript:\n{merged_transcript}"

    # Add image analysis if available
    if image_analysis:
        user_content += f"\n\nImage Recognition:\n{image_analysis}"

    # Add context if available
    if context:
        user_content += f"\n\nContext:\n{context}"

    data = {
        "model": getenv("OPENROUTER_MODEL", "tngtech/deepseek-r1t2-chimera:free"),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }
    import sys

    # Log OpenRouter request (hide API key)
    log_headers = dict(headers)
    if "Authorization" in log_headers:
        log_headers["Authorization"] = "Bearer ***REDACTED***"
    print(f"[OpenRouter REQUEST] URL: {url}", file=sys.stderr)
    print(f"[OpenRouter REQUEST] Headers: {log_headers}", file=sys.stderr)
    print(f"[OpenRouter REQUEST] Payload: {data}", file=sys.stderr)
    resp = requests.post(url, headers=headers, json=data)
    print(f"[OpenRouter RESPONSE] Status: {resp.status_code}", file=sys.stderr)
    print(f"[OpenRouter RESPONSE] Body: {resp.text}", file=sys.stderr)
    try:
        resp.raise_for_status()
    except requests.exceptions.HTTPError:
        if resp.status_code == 404:
            print_flush(
                "ERROR: 404 Not Found from OpenRouter API. This may mean the model name is invalid or unavailable. Please check the OPENROUTER_MODEL environment variable and use a valid model name, such as 'openai/gpt-4o'."
            )
        raise
    summary = resp.json()["choices"][0]["message"]["content"]
    return summary


def maybe_reencode(video_path, tmpdir):
    size_mb = os.path.getsize(video_path) / (1024 * 1024)
    if size_mb > 25:
        reencoded_path = os.path.join(tmpdir, "video_h265.mp4")
        print_flush(f"Re-encoding {video_path} to H.265 (size: {size_mb:.2f}MB)...")
        transcode_timeout = int(getenv("TRANSCODE_TIMEOUT", "600"))
        subprocess.run(
            [
                "ffmpeg",
                "-i",
                video_path,
                "-c:v",
                "libx265",
                "-crf",
                "35",
                "-c:a",
                "copy",
                reencoded_path,
            ],
            check=True,
            timeout=transcode_timeout,
        )
        print_flush(f"Re-encoded video saved to: {reencoded_path}")
        return reencoded_path
    else:
        return video_path


def wait_for_media_processing(mastodon, media_id, timeout=None, poll_interval=2):
    if timeout is None:
        timeout = int(getenv("MASTODON_MEDIA_TIMEOUT", "600"))
    start = time.time()
    while time.time() - start < timeout:
        media = mastodon.media(media_id)
        if media.get("url") and not media.get("processing", False):
            return media
        time.sleep(poll_interval)
    print_flush(
        f"WARNING: Media processing timed out for media_id={media_id}.\n"
        f"Consider increasing the MASTODON_MEDIA_TIMEOUT environment variable or checking your Mastodon instance's limits."
    )
    raise RuntimeError(f"Media processing timed out for media_id={media_id}")


def extract_summary_and_description(ai_response):
    """Extract both the summary and video description from the AI response."""
    import json
    import re

    # First try to parse as JSON
    try:
        # Sometimes AI responses have extra text before/after JSON, so extract JSON block
        json_match = re.search(
            r'\{.*?"summary".*?"video_description".*?\}', ai_response, re.DOTALL
        )
        if json_match:
            json_str = json_match.group(0)
            data = json.loads(json_str)
            summary = data.get("summary", "").strip()
            video_description = data.get("video_description", "").strip()

            # Ensure video description is not longer than 1400 characters
            if len(video_description) > 1400:
                video_description = video_description[:1397] + "..."

            return summary, video_description
    except (json.JSONDecodeError, AttributeError):
        pass

    # Fallback: try the old text-based parsing for backwards compatibility
    # Pattern to find the summary section
    summary_pattern = (
        r"Summary:\s*(.+?)(?=\n\nVideo Description for Visually Impaired:|$)"
    )
    summary_match = re.search(summary_pattern, ai_response, re.DOTALL | re.IGNORECASE)

    # Pattern to find the video description section
    desc_pattern = r"Video Description for Visually Impaired:\s*(.+?)(?:\n\n|$)"
    desc_match = re.search(desc_pattern, ai_response, re.DOTALL | re.IGNORECASE)

    # Extract summary
    if summary_match:
        summary = summary_match.group(1).strip()
    else:
        # Fallback: use everything before "Video Description" or the whole text
        if "Video Description for Visually Impaired:" in ai_response:
            summary = ai_response.split("Video Description for Visually Impaired:")[
                0
            ].strip()
        else:
            # Last fallback: split the response in half
            lines = ai_response.strip().split("\n")
            mid_point = len(lines) // 2
            summary = "\n".join(lines[:mid_point]).strip()

    # Extract video description
    if desc_match:
        description = desc_match.group(1).strip()
        # Ensure it's not longer than 1400 characters
        if len(description) > 1400:
            description = description[:1397] + "..."
    else:
        # Fallback: use the second half or the summary as description
        lines = ai_response.strip().split("\n")
        mid_point = len(lines) // 2
        if len(lines) > mid_point:
            description = "\n".join(lines[mid_point:]).strip()
        else:
            description = summary

        if len(description) > 1400:
            description = description[:1397] + "..."

    return summary, description


# Web Application Classes and Functions
class JobManager:
    def __init__(self):
        self.jobs = {}
        self.lock = threading.Lock()

    def create_job(self, url, enhance=False, dry_run=False):
        job_id = str(uuid.uuid4())
        with self.lock:
            self.jobs[job_id] = {
                "id": job_id,
                "url": url,
                "enhance": enhance,
                "dry_run": dry_run,
                "status": "pending",
                "created_at": datetime.now().isoformat(),
                "progress": "Job created",
                "result": None,
                "error": None,
            }
        return job_id

    def get_job(self, job_id):
        with self.lock:
            return self.jobs.get(job_id)

    def update_job(self, job_id, **kwargs):
        with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id].update(kwargs)

    def list_jobs(self):
        with self.lock:
            return list(self.jobs.values())


def process_video_async(job_manager, job_id):
    def update_progress(status, progress):
        job_manager.update_job(job_id, status=status, progress=progress)

    try:
        job = job_manager.get_job(job_id)
        if not job:
            return

        url = job["url"]
        enhance = job["enhance"]
        dry_run = job["dry_run"]

        update_progress("processing", "Starting video download...")

        with tempfile.TemporaryDirectory() as tmpdir:
            update_progress("processing", "Downloading video...")
            video_path, title, description, uploader, hashtags, platform, mime_type = (
                download_video(url, tmpdir)
            )

            update_progress("processing", "Extracting transcript...")
            transcript = extract_transcript_from_platform(url, tmpdir)

            if transcript:
                update_progress("processing", "Using platform-provided transcript")
            else:
                update_progress("processing", "Transcribing with Whisper...")
                transcript = transcribe_video(video_path)

            if not transcript or (
                isinstance(transcript, str) and transcript.strip() == ""
            ):
                transcript = "[No audio/transcript available]"

            image_analysis = None
            if enhance:
                update_progress("processing", "Analyzing images...")
                try:
                    image_paths = extract_still_images(video_path, tmpdir)
                    image_analysis = analyze_images_with_openrouter(image_paths)
                except Exception as e:
                    print_flush(f"Warning: Image analysis failed: {e}")

            update_progress("processing", "Adding to database...")
            add_to_database(
                uploader,
                title,
                description,
                hashtags,
                platform,
                transcript,
                image_analysis,
            )

            update_progress("processing", "Generating context summary...")
            context = generate_context_summary(uploader)

            update_progress("processing", "Generating AI summary...")
            ai_response = summarize_text(
                transcript, description, uploader, image_analysis, context
            )
            summary, video_description = extract_summary_and_description(ai_response)

            enable_transcoding = os.environ.get("ENABLE_TRANSCODING", "").lower() in (
                "1",
                "true",
                "yes",
            )
            if enable_transcoding:
                update_progress("processing", "Checking if transcoding needed...")
                final_video_path = maybe_reencode(video_path, tmpdir)
            else:
                final_video_path = video_path

            result = {
                "title": title,
                "uploader": uploader,
                "platform": platform,
                "summary": summary,
                "video_description": video_description,
                "transcript": transcript,
                "hashtags": hashtags,
                "source_url": url,
            }

            if dry_run:
                update_progress("completed", "Dry run completed successfully")
                result["mastodon_url"] = None
                result["dry_run"] = True
            else:
                update_progress("processing", "Posting to Mastodon...")
                mastodon_url = post_to_mastodon(
                    summary, final_video_path, url, mime_type, video_description
                )
                result["mastodon_url"] = mastodon_url
                update_progress("completed", "Posted to Mastodon successfully")

            job_manager.update_job(job_id, status="completed", result=result)

    except Exception as e:
        error_msg = str(e)
        print_flush(f"Job {job_id} failed: {error_msg}")
        job_manager.update_job(
            job_id, status="failed", error=error_msg, progress=f"Failed: {error_msg}"
        )


def create_web_app():
    app = Flask(__name__)
    auth = HTTPBasicAuth()
    job_manager = JobManager()

    # Basic auth setup
    @auth.verify_password
    def verify_password(username, password):
        web_user = getenv("WEB_USER")
        web_password = getenv("WEB_PASSWORD")
        if not web_user or not web_password:
            return True  # No auth configured
        return username == web_user and password == web_password

    # Simple HTML interface
    HTML_TEMPLATE = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Ninadon Video Processor</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
            .form-group { margin-bottom: 15px; }
            label { display: block; margin-bottom: 5px; font-weight: bold; }
            input[type="url"], button { padding: 10px; border: 1px solid #ccc; border-radius: 4px; }
            input[type="url"] { width: 100%; box-sizing: border-box; }
            button { background: #007cba; color: white; cursor: pointer; margin-right: 10px; }
            button:hover { background: #005a87; }
            .job { border: 1px solid #ddd; padding: 15px; margin: 10px 0; border-radius: 4px; }
            .status-pending { border-left: 4px solid #ffa500; }
            .status-processing { border-left: 4px solid #007cba; }
            .status-completed { border-left: 4px solid #28a745; }
            .status-failed { border-left: 4px solid #dc3545; }
            .result { background: #f8f9fa; padding: 10px; margin-top: 10px; border-radius: 4px; }
        </style>
    </head>
    <body>
        <h1>Ninadon Video Processor</h1>
        <form id="videoForm">
            <div class="form-group">
                <label for="url">Video URL (YouTube, TikTok, Instagram):</label>
                <input type="url" id="url" name="url" required placeholder="https://...">
            </div>
            <div class="form-group">
                <label>
                    <input type="checkbox" id="enhance" name="enhance"> Enable image analysis
                </label>
            </div>
            <div class="form-group">
                <label>
                    <input type="checkbox" id="dry_run" name="dry_run"> Dry run (don't post to Mastodon)
                </label>
            </div>
            <button type="submit">Process Video</button>
            <button type="button" onclick="refreshJobs()">Refresh Status</button>
        </form>
        
        <h2>Jobs</h2>
        <div id="jobs"></div>
        
        <script>
            document.getElementById('videoForm').onsubmit = function(e) {
                e.preventDefault();
                const formData = new FormData(e.target);
                const data = {
                    url: formData.get('url'),
                    enhance: formData.get('enhance') === 'on',
                    dry_run: formData.get('dry_run') === 'on'
                };
                
                fetch('/api/process', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(data)
                })
                .then(r => r.json())
                .then(data => {
                    if (data.job_id) {
                        alert('Job created: ' + data.job_id);
                        refreshJobs();
                    } else {
                        alert('Error: ' + (data.error || 'Unknown error'));
                    }
                })
                .catch(e => alert('Error: ' + e));
            };
            
            function refreshJobs() {
                fetch('/api/jobs')
                .then(r => r.json())
                .then(jobs => {
                    const container = document.getElementById('jobs');
                    if (jobs.length === 0) {
                        container.innerHTML = '<p>No jobs yet.</p>';
                        return;
                    }
                    
                    container.innerHTML = jobs.map(job => `
                        <div class="job status-${job.status}">
                            <strong>Job ${job.id.substring(0, 8)}</strong> - ${job.status}
                            <br>URL: ${job.url}
                            <br>Progress: ${job.progress}
                            <br>Created: ${new Date(job.created_at).toLocaleString()}
                            ${job.error ? '<br><strong>Error:</strong> ' + job.error : ''}
                            ${job.result ? '<div class="result"><strong>Result:</strong><br>' + 
                                'Title: ' + job.result.title + '<br>' +
                                'Summary: ' + job.result.summary + '<br>' +
                                (job.result.mastodon_url ? 'Mastodon: <a href="' + job.result.mastodon_url + '" target="_blank">' + job.result.mastodon_url + '</a>' : 'Dry run completed') +
                            '</div>' : ''}
                        </div>
                    `).join('');
                });
            }
            
            // Refresh jobs every 5 seconds
            setInterval(refreshJobs, 5000);
            refreshJobs();
        </script>
    </body>
    </html>
    """

    @app.route("/")
    @auth.login_required
    def index():
        return HTML_TEMPLATE

    @app.route("/api/process", methods=["POST"])
    @auth.login_required
    def api_process():
        try:
            data = request.get_json()
            if not data or "url" not in data:
                return jsonify({"error": "URL is required"}), 400

            url = data["url"]
            enhance = data.get("enhance", False)
            dry_run = data.get("dry_run", False)

            job_id = job_manager.create_job(url, enhance, dry_run)

            # Start processing in background thread
            thread = threading.Thread(
                target=process_video_async, args=(job_manager, job_id)
            )
            thread.daemon = True
            thread.start()

            return jsonify({"job_id": job_id, "status": "created"})

        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/jobs", methods=["GET"])
    @auth.login_required
    def api_jobs():
        jobs = job_manager.list_jobs()
        # Sort by creation time, newest first
        jobs.sort(key=lambda x: x["created_at"], reverse=True)
        return jsonify(jobs)

    @app.route("/api/status/<job_id>", methods=["GET"])
    @auth.login_required
    def api_status(job_id):
        job = job_manager.get_job(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        return jsonify(job)

    return app


def extract_video_description(summary_text):
    """Extract the video description for visually impaired from the AI summary."""
    _, description = extract_summary_and_description(summary_text)
    return description


def post_to_mastodon(
    summary, video_path, source_url, mime_type=None, video_description=None
):
    size_bytes = os.path.getsize(video_path)
    size_mb = size_bytes / (1024 * 1024)
    print_flush(
        f"Video file size before posting: {size_mb:.2f} MB ({size_bytes} bytes)"
    )
    auth_token = getenv("AUTH_TOKEN", required=True)
    mastodon_url = getenv("MASTODON_URL", "https://mastodon.social")
    mastodon = Mastodon(access_token=auth_token, api_base_url=mastodon_url)
    print_flush("Uploading video to Mastodon...")
    # ProgressFile class is not used, so removed for clarity
    # Determine mime type if not provided
    if not mime_type:
        mime_type, _ = mimetypes.guess_type(video_path)
        if not mime_type:
            mime_type = "application/octet-stream"
    media = mastodon.media_post(
        video_path, mime_type=mime_type, description=video_description
    )
    print_flush("Waiting for Mastodon to process video...")
    mastodon_timeout = int(getenv("MASTODON_MEDIA_TIMEOUT", "600"))
    print_flush(f"Mastodon media processing timeout: {mastodon_timeout} seconds")
    media = wait_for_media_processing(mastodon, media["id"])
    print_flush("Posting status to Mastodon...")
    status_text = f"{summary}\n\nSource: {source_url}"
    print_flush(f"Mastodon post text length: {len(status_text)} characters")
    print_flush(f"Mastodon post text:\n{status_text}")
    status = mastodon.status_post(status_text, media_ids=[media["id"]])
    print_flush(f"Posted to Mastodon: {status['url']}")
    return status["url"]


def main():
    parser = argparse.ArgumentParser(
        description="Download, transcribe, summarize, and post video."
    )
    parser.add_argument("url", nargs="?", help="Video URL (YouTube, Instagram, TikTok)")
    parser.add_argument(
        "--dry", action="store_true", help="Perform dry run without posting to Mastodon"
    )
    parser.add_argument(
        "--enhance",
        action="store_true",
        help="Extract still images and analyze them for enhanced summarization",
    )
    parser.add_argument(
        "--download-whisper-model",
        metavar="MODEL",
        nargs="?",
        const="base",
        help="Download a Whisper model (default: base). Available models: tiny, base, small, medium, large",
    )
    parser.add_argument("--web", action="store_true", help="Start web server mode")
    parser.add_argument(
        "--port", type=int, default=5000, help="Web server port (default: 5000)"
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Web server host (default: 127.0.0.1)"
    )
    args = parser.parse_args()

    # Handle web server mode
    if args.web:
        print_flush("Starting Ninadon web server...")
        print_flush(f"Server will run on http://{args.host}:{args.port}")

        web_user = getenv("WEB_USER")
        web_password = getenv("WEB_PASSWORD")
        if web_user and web_password:
            print_flush(f"Basic auth enabled for user: {web_user}")
        else:
            print_flush(
                "WARNING: No basic auth configured. Set WEB_USER and WEB_PASSWORD environment variables for security."
            )

        app = create_web_app()
        try:
            app.run(host=args.host, port=args.port, debug=False)
        except KeyboardInterrupt:
            print_flush("\nShutting down web server...")
        return

    # Handle model download command
    if args.download_whisper_model is not None:
        try:
            download_whisper_model(args.download_whisper_model)
            print_flush(
                f"Whisper model '{args.download_whisper_model}' downloaded successfully"
            )
            return
        except Exception as e:
            print_flush(
                f"Failed to download Whisper model '{args.download_whisper_model}': {e}"
            )
            return 1

    # Require URL for normal operation
    if not args.url:
        parser.error(
            "URL is required for video processing. Use --download-whisper-model to download models only, or --web to start web server."
        )

    with tempfile.TemporaryDirectory() as tmpdir:

        print_flush(f"Working in temp dir: {tmpdir}")
        print_flush("Starting download...")
        video_path, title, description, uploader, hashtags, platform, mime_type = (
            download_video(args.url, tmpdir)
        )
        print_flush(f"Downloaded video to: {video_path}")
        print_flush(f"Title: {title}")
        print_flush(f"Uploader: {uploader}")
        print_flush(f"Platform: {platform}")
        print_flush(f"Description: {description}")
        print_flush(f"Hashtags: {hashtags}")

        # Try to get transcript from platform first, fallback to whisper
        print_flush("Starting transcription...")
        transcript = extract_transcript_from_platform(args.url, tmpdir)

        if transcript:
            print_flush("Using platform-provided transcript")
        else:
            print_flush("No platform transcript available, using whisper...")
            transcript = transcribe_video(video_path)

        # Handle case where no audio/transcript is available
        if not transcript or (isinstance(transcript, str) and transcript.strip() == ""):
            print_flush("No transcript available (video may be audio-free)")
            transcript = "[No audio/transcript available]"

        print_flush(f"Transcript:\n{transcript}")

        # Handle image analysis if --enhance flag is used
        image_analysis = None
        if args.enhance:
            print_flush("Starting image extraction and analysis...")
            try:
                image_paths = extract_still_images(video_path, tmpdir)
                image_analysis = analyze_images_with_openrouter(image_paths)
                print_flush(f"Image Analysis:\n{image_analysis}")
            except Exception as e:
                print_flush(f"Warning: Image analysis failed: {e}")
                print_flush("Continuing with transcript-only summarization...")

        # Add current video to database
        print_flush("Adding video to database...")
        add_to_database(
            uploader, title, description, hashtags, platform, transcript, image_analysis
        )

        # Generate context summary from database
        print_flush("Generating context summary...")
        context = generate_context_summary(uploader)
        if context:
            print_flush(f"Context:\n{context}")
        else:
            print_flush("No context available")

        print_flush("Starting summarization...")
        ai_response = summarize_text(
            transcript, description, uploader, image_analysis, context
        )
        print_flush(f"AI Response:\n{ai_response}")

        # Extract summary and video description separately
        summary, video_description = extract_summary_and_description(ai_response)
        print_flush(f"Summary for Toot:\n{summary}")
        print_flush(
            f"Video description for visually impaired ({len(video_description)} chars):\n{video_description}"
        )
        enable_transcoding = os.environ.get("ENABLE_TRANSCODING", "").lower() in (
            "1",
            "true",
            "yes",
        )
        if enable_transcoding:
            print_flush("Transcoding is enabled. Checking if transcoding is needed...")
            final_video_path = maybe_reencode(video_path, tmpdir)
        else:
            print_flush("Transcoding is disabled. Using original video.")
            final_video_path = video_path
        print_flush(f"Final video for posting: {final_video_path}")
        if args.dry:
            print_flush("DRY RUN: Skipping Mastodon post")
            print_flush(f"Would post summary:\n{summary}")
            print_flush(f"Would post video: {final_video_path}")
            print_flush(f"Would include source URL: {args.url}")
            print_flush(f"Would use video description: {video_description}")
        else:
            print_flush("Starting Mastodon post...")
            mastodon_url = post_to_mastodon(
                summary, final_video_path, args.url, mime_type, video_description
            )
            print_flush(f"Mastodon post URL: {mastodon_url}")
        # Temp files are cleaned up automatically


if __name__ == "__main__":
    main()
