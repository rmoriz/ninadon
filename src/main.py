#!/usr/bin/env python3
import warnings
warnings.filterwarnings("ignore", message="FP16 is not supported on CPU; using FP32 instead")
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
    # Step 1: Extract info without downloading
    ydl_opts_info = {'quiet': True}
    with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
        info = ydl.extract_info(url, download=False)
    # Step 2: Find best muxed or video+audio pair <100MB, else smallest
    formats = info.get('formats', [])
    muxed = []
    videos = []
    audios = []
    for f in formats:
        # Only consider formats with a valid url (directly downloadable)
        if not f.get('url'):
            continue
        size = f.get('filesize') or f.get('filesize_approx')
        if not size:
            continue
        if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
            muxed.append((size, f))
        elif f.get('vcodec') != 'none':
            videos.append((size, f))
        elif f.get('acodec') != 'none':
            audios.append((size, f))
    # Alle muxed-Formate prüfen
    candidates = []
    for size, f in muxed:
        candidates.append((size, f['format_id']))
    # Alle Video+Audio-Kombis prüfen
    for vsize, v in videos:
        for asize, a in audios:
            total = vsize + asize
            # yt-dlp Format-String: "video_id+audio_id"
            candidates.append((total, f"{v['format_id']}+{a['format_id']}"))
    # Unter 100MB suchen
    under_100mb = [c for c in candidates if c[0] < 100*1024*1024]
    if candidates:
        if under_100mb:
            selected = max(under_100mb, key=lambda x: x[0])
        else:
            selected = min(candidates, key=lambda x: x[0])
        format_id = selected[1]
        # Step 3: Download the selected format or pair
        ydl_opts = {
            'outtmpl': outtmpl,
            'format': format_id,
            'merge_output_format': 'mp4',
            'quiet': True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if 'requested_downloads' in info:
                    filepath = info['requested_downloads'][0]['filepath']
                else:
                    filepath = ydl.prepare_filename(info)
        except Exception as e:
            print(f"Error downloading selected format: {e}\nFalling back to 'best' format.")
            ydl_opts['format'] = 'best'
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if 'requested_downloads' in info:
                    filepath = info['requested_downloads'][0]['filepath']
                else:
                    filepath = ydl.prepare_filename(info)
    else:
        print("No directly downloadable formats found! Available formats:")
        for f in formats:
            print(f"format_id={f.get('format_id')}, vcodec={f.get('vcodec')}, acodec={f.get('acodec')}, filesize={f.get('filesize')}, url={'yes' if f.get('url') else 'no'}")
        print("Falling back to 'best' format.")
        ydl_opts = {
            'outtmpl': outtmpl,
            'format': 'best',
            'merge_output_format': 'mp4',
            'quiet': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if 'requested_downloads' in info:
                filepath = info['requested_downloads'][0]['filepath']
            else:
                filepath = ydl.prepare_filename(info)
    description = info.get('description', '')
    uploader = info.get('uploader', info.get('channel', info.get('author', '')))
    return filepath, description, uploader


def transcribe_video(video_path):
    model = whisper.load_model("base")
    result = model.transcribe(video_path)
    return result["text"]


def summarize_text(transcript, description, uploader):
    system_prompt = os.environ.get("SYSTEM_PROMPT", "Summarize the following video transcript, description, and account name:")
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY environment variable not set")
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    user_content = f"Account name: {uploader}\nDescription: {description}\nTranscript:\n{transcript}"
    data = {
        "model": "openrouter/horizon-alpha",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
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
        transcode_timeout = int(os.environ.get("TRANSCODE_TIMEOUT", "600"))
        subprocess.run([
            "ffmpeg", "-i", video_path, "-c:v", "libx265", "-crf", "35", "-c:a", "copy", reencoded_path
        ], check=True, timeout=transcode_timeout)
        print(f"Re-encoded video saved to: {reencoded_path}")
        return reencoded_path
    else:
        return video_path


import time

def wait_for_media_processing(mastodon, media_id, timeout=None, poll_interval=2):
    if timeout is None:
        timeout = int(os.environ.get("MASTODON_MEDIA_TIMEOUT", "180"))
    """Poll Mastodon media status until processed or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        media = mastodon.media(media_id)
        # Mastodon returns 'url' when processed, and 'processing' is False
        if media.get("url") and not media.get("processing", False):
            return media
        time.sleep(poll_interval)
    raise RuntimeError("Media processing timed out")

def post_to_mastodon(summary, video_path, source_url):
    size_bytes = os.path.getsize(video_path)
    size_mb = size_bytes / (1024 * 1024)
    print(f"Video file size before posting: {size_mb:.2f} MB ({size_bytes} bytes)")
    auth_token = os.environ.get("AUTH_TOKEN")
    mastodon_url = os.environ.get("MASTODON_URL", "https://mastodon.social")
    if not auth_token:
        raise RuntimeError("AUTH_TOKEN environment variable not set")
    mastodon = Mastodon(access_token=auth_token, api_base_url=mastodon_url)
    print(f"Uploading video to Mastodon...")
    media = mastodon.media_post(video_path, mime_type="video/mp4")
    print(f"Waiting for Mastodon to process video...")
    media = wait_for_media_processing(mastodon, media["id"])
    print(f"Posting status to Mastodon...")
    status_text = f"{summary}\n\nSource: {source_url}"
    print(f"Mastodon post text length: {len(status_text)} characters")
    print(f"Mastodon post text:\n{status_text}")
    status = mastodon.status_post(status_text, media_ids=[media["id"]])
    print(f"Posted to Mastodon: {status['url']}")
    return status['url']


def main():
    parser = argparse.ArgumentParser(description="Download, transcribe, summarize, and post video.")
    parser.add_argument('url', help='Video URL (YouTube, Instagram, TikTok)')
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Working in temp dir: {tmpdir}")
        print("Starting download...")
        video_path, description, uploader = download_video(args.url, tmpdir)
        print(f"Downloaded video to: {video_path}")
        print(f"Uploader: {uploader}")
        print(f"Description: {description}")
        print("Starting transcription...")
        transcript = transcribe_video(video_path)
        print(f"Transcript:\n{transcript}")
        print("Starting summarization...")
        summary = summarize_text(transcript, description, uploader)
        print(f"Summary:\n{summary}")
        enable_transcoding = os.environ.get("ENABLE_TRANSCODING", "").lower() in ("1", "true", "yes")
        if enable_transcoding:
            print("Transcoding is enabled. Checking if transcoding is needed...")
            final_video_path = maybe_reencode(video_path, tmpdir)
        else:
            print("Transcoding is disabled. Using original video.")
            final_video_path = video_path
        print(f"Final video for posting: {final_video_path}")
        print("Starting Mastodon post...")
        mastodon_url = post_to_mastodon(summary, final_video_path, args.url)
        print(f"Mastodon post URL: {mastodon_url}")
        # Temp files are cleaned up automatically

if __name__ == "__main__":
    main()
