#!/usr/bin/env python3
"""
Ninadon - Video processing and social media posting tool.
Refactored modular version.
"""

import argparse
import tempfile
import warnings

from .ai_services import (
    extract_summary_and_description,
    generate_context_summary,
    summarize_text,
)
from .config import Config
from .database import add_to_database
from .image_analysis import analyze_images_with_openrouter, extract_still_images
from .mastodon_client import post_to_mastodon
from .transcription import extract_transcript_from_platform, transcribe_video
from .utils import print_flush
from .video_downloader import download_video
from .video_processing import maybe_reencode
from .web_app import create_web_app

warnings.filterwarnings(
    "ignore", message="FP16 is not supported on CPU; using FP32 instead"
)


def process_video(url, enhance=False, dry_run=False):
    """
    Process a single video URL.

    Args:
        url: Video URL to process
        enhance: Whether to perform image analysis
        dry_run: Whether to skip posting to Mastodon

    Returns:
        dict: Processing results
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        print_flush("Starting video processing...")

        # Download video and extract metadata
        print_flush("Downloading video...")
        video_path, title, description, uploader, hashtags, platform, mime_type = (
            download_video(url, tmpdir)
        )

        # Try to get transcript from platform first
        print_flush("Extracting transcript...")
        transcript = extract_transcript_from_platform(url, tmpdir)

        if transcript:
            print_flush("Using platform-provided transcript")
        else:
            print_flush("Transcribing with Whisper...")
            transcript = transcribe_video(video_path)

        if not transcript or (isinstance(transcript, str) and transcript.strip() == ""):
            transcript = "[No audio/transcript available]"

        # Perform image analysis if requested
        image_analysis = None
        if enhance:
            print_flush("Analyzing images...")
            try:
                image_paths = extract_still_images(video_path, tmpdir)
                image_analysis = analyze_images_with_openrouter(image_paths)
            except Exception as e:
                print_flush(f"Warning: Image analysis failed: {e}")

        # Store in database
        print_flush("Adding to database...")
        add_to_database(
            uploader, title, description, hashtags, platform, transcript, image_analysis
        )

        # Generate context summary
        print_flush("Generating context summary...")
        context = generate_context_summary(uploader)

        # Generate AI summary
        print_flush("Generating AI summary...")
        ai_response = summarize_text(
            transcript, description, uploader, image_analysis, context
        )
        summary, video_description = extract_summary_and_description(ai_response)

        # Handle video transcoding if enabled
        if Config.ENABLE_TRANSCODING:
            print_flush("Checking if transcoding needed...")
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

        # Post to Mastodon unless dry run
        if dry_run:
            print_flush("Dry run mode - skipping Mastodon post")
            result["mastodon_url"] = None
            result["dry_run"] = True
        else:
            print_flush("Posting to Mastodon...")
            mastodon_url = post_to_mastodon(
                summary, final_video_path, url, mime_type, video_description
            )
            result["mastodon_url"] = mastodon_url
            print_flush(f"Posted successfully: {mastodon_url}")

        return result


def main():
    """Main entry point."""
    from . import __version__

    parser = argparse.ArgumentParser(description="Process videos and post to Mastodon")
    parser.add_argument("url", nargs="?", help="Video URL to process")
    parser.add_argument("--enhance", action="store_true", help="Enable image analysis")
    parser.add_argument("--dry-run", action="store_true", help="Don't post to Mastodon")
    parser.add_argument("--web", action="store_true", help="Start web interface")
    parser.add_argument(
        "--port", type=int, default=Config.WEB_PORT, help="Web interface port"
    )
    parser.add_argument("--version", action="version", version=f"Ninadon {__version__}")

    args = parser.parse_args()

    if args.web:
        print_flush(f"Starting web interface on port {args.port}")
        app = create_web_app()
        app.run(host="0.0.0.0", port=args.port, debug=False)
    elif args.url:
        try:
            result = process_video(args.url, enhance=args.enhance, dry_run=args.dry_run)
            print_flush("Processing completed successfully!")
            print_flush(f"Title: {result['title']}")
            print_flush(f"Summary: {result['summary']}")
            if result.get("mastodon_url"):
                print_flush(f"Mastodon URL: {result['mastodon_url']}")
        except Exception as e:
            print_flush(f"Error processing video: {e}")
            exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
