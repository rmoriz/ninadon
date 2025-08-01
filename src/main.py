#!/usr/bin/env python3
import argparse
import tempfile
import os
import yt_dlp
import whisper
import requests
import subprocess
from mastodon import Mastodon


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


def transcribe_video(video_path):
    model = whisper.load_model("base")
    result = model.transcribe(video_path)
    return result["text"]


def summarize_text(transcript):
    system_prompt = os.environ.get("SYSTEM_PROMPT", "Summarize the following video transcript:")
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY environment variable not set")
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Text:\n{transcript}"}
        ]
    }
    resp = requests.post(url, headers=headers, json=data)
    resp.raise_for_status()
    summary = resp.json()["choices"][0]["message"]["content"]
    return summary


def maybe_reencode(video_path, tmpdir):
    size_mb = os.path.getsize(video_path) / (1024 * 1024)
    if size_mb > 25:
        reencoded_path = os.path.join(tmpdir, "video_h265.mp4")
        print(f"Re-encoding {video_path} to H.265 (size: {size_mb:.2f}MB)...")
        subprocess.run([
            "ffmpeg", "-i", video_path, "-c:v", "libx265", "-crf", "35", "-c:a", "copy", reencoded_path
        ], check=True)
        print(f"Re-encoded video saved to: {reencoded_path}")
        return reencoded_path
    else:
        return video_path


def post_to_mastodon(summary, video_path):
    auth_token = os.environ.get("AUTH_TOKEN")
    mastodon_url = os.environ.get("MASTODON_URL", "https://mastodon.social")
    if not auth_token:
        raise RuntimeError("AUTH_TOKEN environment variable not set")
    mastodon = Mastodon(access_token=auth_token, api_base_url=mastodon_url)
    print(f"Uploading video to Mastodon...")
    media = mastodon.media_post(video_path, mime_type="video/mp4")
    print(f"Posting status to Mastodon...")
    status = mastodon.status_post(summary, media_ids=[media["id"]])
    print(f"Posted to Mastodon: {status['url']}")
    return status['url']


def main():
    parser = argparse.ArgumentParser(description="Download, transcribe, summarize, and post video.")
    parser.add_argument('url', help='Video URL (YouTube, Instagram, TikTok)')
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Working in temp dir: {tmpdir}")
        video_path = download_video(args.url, tmpdir)
        print(f"Downloaded video to: {video_path}")
        transcript = transcribe_video(video_path)
        print(f"Transcript:\n{transcript}")
        summary = summarize_text(transcript)
        print(f"Summary:\n{summary}")
        final_video_path = maybe_reencode(video_path, tmpdir)
        print(f"Final video for posting: {final_video_path}")
        mastodon_url = post_to_mastodon(summary, final_video_path)
        print(f"Mastodon post URL: {mastodon_url}")
        # Temp files are cleaned up automatically

if __name__ == "__main__":
    main()
