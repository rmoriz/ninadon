#!/usr/bin/env python3
"""Mastodon client for posting videos and status updates."""

import time

from mastodon import Mastodon

from .config import Config
from .utils import print_flush


def wait_for_media_processing(mastodon, media_id, timeout=None, poll_interval=2):
    """Wait for Mastodon media processing to complete."""
    if timeout is None:
        timeout = Config.MASTODON_MEDIA_TIMEOUT
    start = time.time()
    while time.time() - start < timeout:
        media = mastodon.media(media_id)
        if media.get("url") and not media.get("processing", False):
            return media
        time.sleep(poll_interval)
    print_flush(
        f"WARNING: Media processing timed out for media_id={media_id}.\n"
        "Consider increasing the MASTODON_MEDIA_TIMEOUT environment variable."
    )
    raise RuntimeError(f"Media processing timed out for media_id={media_id}")


def post_to_mastodon(summary, video_path, source_url, mime_type, video_description):
    """Post video and summary to Mastodon."""
    config = Config()
    mastodon = Mastodon(
        access_token=config.MASTODON_ACCESS_TOKEN, api_base_url=config.MASTODON_BASE_URL
    )

    print_flush("Uploading video to Mastodon...")
    media = mastodon.media_post(
        video_path, mime_type=mime_type, description=video_description
    )
    media_id = media["id"]
    print_flush(f"Video uploaded with media_id: {media_id}")

    print_flush("Waiting for media processing...")
    processed_media = wait_for_media_processing(mastodon, media_id)
    print_flush(f"Media processed successfully: {processed_media.get('url')}")

    status_text = f"{summary}\n\nSource: {source_url}"
    print_flush("Posting status to Mastodon...")
    status = mastodon.status_post(status_text, media_ids=[media_id])
    mastodon_url = status["url"]
    print_flush(f"Status posted successfully: {mastodon_url}")

    return mastodon_url
