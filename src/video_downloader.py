#!/usr/bin/env python3
"""Video downloading functionality using yt-dlp."""

import json
import os
import re
import subprocess

import yt_dlp

from .utils import print_flush


def run_ydl(url, ydl_opts, download):
    """Execute yt-dlp with given options."""
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=download)
        return info, ydl


def collect_formats(formats):
    """Categorize video formats into muxed, video-only, and audio-only."""
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
    """Build list of download candidates with total sizes."""
    candidates = [(size, f["format_id"]) for size, f in muxed]
    for vsize, v in videos:
        for asize, a in audios:
            total = vsize + asize
            candidates.append((total, f"{v['format_id']}+{a['format_id']}"))
    return candidates


def select_filepath(info, ydl):
    """Select the downloaded file path from yt-dlp info."""
    if "requested_downloads" in info:
        return info["requested_downloads"][0]["filepath"]
    else:
        return ydl.prepare_filename(info)


def fix_downloaded_filepath(filepath, tmpdir):
    """Fix problematic file paths after download, especially .NA extensions."""
    # Check if the file exists as-is and is not a .NA file
    if filepath and os.path.exists(filepath) and not filepath.endswith(".NA"):
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


def determine_platform(url):
    """Determine the platform from the URL."""
    url_lower = url.lower()
    if "tiktok.com" in url_lower:
        return "tiktok"
    elif "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    elif "instagram.com" in url_lower:
        return "instagram"
    return "unknown"


def extract_hashtags(title, description):
    """Extract hashtags from title and description."""
    text_to_search = f"{title} {description}"
    hashtag_matches = re.findall(r"#\w+", text_to_search)
    return list(set(hashtag_matches))  # Remove duplicates


def download_video(url, tmpdir):
    """
    Download video from URL and extract metadata.

    Returns:
        tuple: (filepath, title, description, uploader, hashtags, platform, mime_type)
    """
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
                    f"format_id={f.get('format_id')}, vcodec={f.get('vcodec')}, "
                    f"acodec={f.get('acodec')}, filesize={f.get('filesize')}, "
                    f"url={'yes' if f.get('url') else 'no'}"
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
    hashtags = extract_hashtags(title, description)

    # Determine platform from URL
    platform = determine_platform(url)

    # Get MIME type
    mime_type = None
    if "requested_downloads" in info and info["requested_downloads"]:
        mime_type = info["requested_downloads"][0].get("mime_type")
    if not mime_type:
        mime_type = info.get("mime_type")

    return filepath, title, description, uploader, hashtags, platform, mime_type
