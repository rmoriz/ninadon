#!/usr/bin/env python3
import argparse
import tempfile
import os
import yt_dlp


def download_video(url, tmpdir):
    outtmpl = os.path.join(tmpdir, 'video.%(ext)s')
    ydl_opts = {
        'outtmpl': outtmpl,
        'format': 'bestvideo+bestaudio/best',
        'merge_output_format': 'mp4',
        'quiet': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        # Get the actual file path after post-processing
        if 'requested_downloads' in info:
            filepath = info['requested_downloads'][0]['filepath']
        else:
            filepath = ydl.prepare_filename(info)
    return filepath


def main():
    parser = argparse.ArgumentParser(description="Download, transcribe, summarize, and post video.")
    parser.add_argument('url', help='Video URL (YouTube, Instagram, TikTok)')
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Working in temp dir: {tmpdir}")
        video_path = download_video(args.url, tmpdir)
        print(f"Downloaded video to: {video_path}")
        # TODO: Transcribe, summarize, post, cleanup

if __name__ == "__main__":
    main()
