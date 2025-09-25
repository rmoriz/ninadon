#!/usr/bin/env python3
"""Video processing utilities including transcoding."""

import os
import subprocess

from .config import Config
from .utils import print_flush


def maybe_reencode(video_path, tmpdir):
    """Re-encode video to H.265 if it's larger than 25MB."""
    size_mb = os.path.getsize(video_path) / (1024 * 1024)
    if size_mb > 25:
        reencoded_path = os.path.join(tmpdir, "video_h265.mp4")
        print_flush(f"Re-encoding {video_path} to H.265 (size: {size_mb:.2f}MB)...")
        subprocess.run(
            ["ffmpeg", "-i", video_path, "-c:v", "libx265", "-crf", "35", "-c:a", "copy", reencoded_path],
            check=True,
            timeout=Config.TRANSCODE_TIMEOUT,
        )
        print_flush(f"Re-encoded video saved to: {reencoded_path}")
        return reencoded_path
    else:
        return video_path
