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
import time
import mimetypes

def run_ydl(url, ydl_opts, download):
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=download)
        return info, ydl

def collect_formats(formats):
    muxed, videos, audios = [], [], []
    for f in formats:
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
    return muxed, videos, audios

def build_candidates(muxed, videos, audios):
    candidates = [(size, f['format_id']) for size, f in muxed]
    for vsize, v in videos:
        for asize, a in audios:
            total = vsize + asize
            candidates.append((total, f"{v['format_id']}+{a['format_id']}"))
    return candidates

def select_filepath(info, ydl):
    if 'requested_downloads' in info:
        return info['requested_downloads'][0]['filepath']
    else:
        return ydl.prepare_filename(info)

def download_video(url, tmpdir):
    outtmpl = os.path.join(tmpdir, 'video.%(ext)s')
    ydl_opts_info = {'quiet': True}
    info, _ydl = run_ydl(url, ydl_opts_info, False)
    formats = info.get('formats', [])
    muxed, videos, audios = collect_formats(formats)
    candidates = build_candidates(muxed, videos, audios)
    under_30mb = [c for c in candidates if c[0] < 30*1024*1024]
    if candidates:
        if under_30mb:
            selected = max(under_30mb, key=lambda x: x[0])
        else:
            selected = min(candidates, key=lambda x: x[0])
        format_id = selected[1]
        ydl_opts = {
            'outtmpl': outtmpl,
            'format': format_id,
            'merge_output_format': 'mp4',
            'quiet': True,
        }
        try:
            info, ydl = run_ydl(url, ydl_opts, True)
            filepath = select_filepath(info, ydl)
        except Exception as e:
            print_flush(f"Error downloading selected format: {e}\nFalling back to 'best' format.")
            ydl_opts['format'] = 'best'
            info, ydl = run_ydl(url, ydl_opts, True)
            filepath = select_filepath(info, ydl)
    else:
        print_flush("No directly downloadable formats found! Available formats:")
        for f in formats:
            print_flush(f"format_id={f.get('format_id')}, vcodec={f.get('vcodec')}, acodec={f.get('acodec')}, filesize={f.get('filesize')}, url={'yes' if f.get('url') else 'no'}")
        print_flush("Falling back to 'best' format.")
        ydl_opts = {
            'outtmpl': outtmpl,
            'format': 'best',
            'merge_output_format': 'mp4',
            'quiet': True,
        }
        info, ydl = run_ydl(url, ydl_opts, True)
        filepath = select_filepath(info, ydl)
    description = info.get('description', '')
    uploader = info.get('uploader', info.get('channel', info.get('author', '')))
    mime_type = None
    if 'requested_downloads' in info and info['requested_downloads']:
        mime_type = info['requested_downloads'][0].get('mime_type')
    if not mime_type:
        mime_type = info.get('mime_type')
    return filepath, description, uploader, mime_type

def transcribe_video(video_path):
    model = whisper.load_model("base")
    result = model.transcribe(video_path)
    return result["text"]

def getenv(key, default=None, required=False):
    val = os.environ.get(key, default)
    if required and not val:
        raise RuntimeError(f"{key} environment variable not set")
    return val

def summarize_text(transcript, description, uploader):
    system_prompt = getenv("SYSTEM_PROMPT", "Summarize the following video transcript, description, and account name:")
    api_key = getenv("OPENROUTER_API_KEY", required=True)
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "Ninadon",
        "HTTP-Referer": "https://github.com/rmoriz/ninadon"
    }
    user_prompt = getenv("USER_PROMPT", "")
    merged_transcript = f"{user_prompt}\n\n{transcript}" if user_prompt else transcript
    user_content = f"Account name: {uploader}\nDescription: {description}\nTranscript:\n{merged_transcript}"
    data = {
        "model": getenv("OPENROUTER_MODEL", "openrouter/horizon-beta"),
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
        print_flush(f"Re-encoding {video_path} to H.265 (size: {size_mb:.2f}MB)...")
        transcode_timeout = int(getenv("TRANSCODE_TIMEOUT", "600"))
        subprocess.run([
            "ffmpeg", "-i", video_path, "-c:v", "libx265", "-crf", "35", "-c:a", "copy", reencoded_path
        ], check=True, timeout=transcode_timeout)
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
    print_flush(f"WARNING: Media processing timed out for media_id={media_id}.\n"
               f"Consider increasing the MASTODON_MEDIA_TIMEOUT environment variable or checking your Mastodon instance's limits.")
    raise RuntimeError(f"Media processing timed out for media_id={media_id}")

def print_flush(*args, **kwargs):
    import builtins
    builtins.print(*args, **kwargs)
    import sys; sys.stdout.flush()

def post_to_mastodon(summary, video_path, source_url, mime_type=None):
    size_bytes = os.path.getsize(video_path)
    size_mb = size_bytes / (1024 * 1024)
    print_flush(f"Video file size before posting: {size_mb:.2f} MB ({size_bytes} bytes)")
    auth_token = getenv("AUTH_TOKEN", required=True)
    mastodon_url = getenv("MASTODON_URL", "https://mastodon.social")
    mastodon = Mastodon(access_token=auth_token, api_base_url=mastodon_url)
    print_flush(f"Uploading video to Mastodon...")
    # ProgressFile class is not used, so removed for clarity
    # Determine mime type if not provided
    if not mime_type:
        mime_type, _ = mimetypes.guess_type(video_path)
        if not mime_type:
            mime_type = "application/octet-stream"
    media = mastodon.media_post(video_path, mime_type=mime_type)
    print_flush(f"Waiting for Mastodon to process video...")
    mastodon_timeout = int(getenv("MASTODON_MEDIA_TIMEOUT", "600"))
    print_flush(f"Mastodon media processing timeout: {mastodon_timeout} seconds")
    media = wait_for_media_processing(mastodon, media["id"])
    print_flush(f"Posting status to Mastodon...")
    status_text = f"{summary}\n\nSource: {source_url}"
    print_flush(f"Mastodon post text length: {len(status_text)} characters")
    print_flush(f"Mastodon post text:\n{status_text}")
    status = mastodon.status_post(status_text, media_ids=[media["id"]])
    print_flush(f"Posted to Mastodon: {status['url']}")
    return status['url']

def main():
    parser = argparse.ArgumentParser(description="Download, transcribe, summarize, and post video.")
    parser.add_argument('url', help='Video URL (YouTube, Instagram, TikTok)')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmpdir:
        import sys
        print_flush(f"Working in temp dir: {tmpdir}")
        print_flush("Starting download...")
        video_path, description, uploader, mime_type = download_video(args.url, tmpdir)
        print_flush(f"Downloaded video to: {video_path}")
        print_flush(f"Uploader: {uploader}")
        print_flush(f"Description: {description}")
        print_flush("Starting transcription...")
        transcript = transcribe_video(video_path)
        print_flush(f"Transcript:\n{transcript}")
        print_flush("Starting summarization...")
        summary = summarize_text(transcript, description, uploader)
        print_flush(f"Summary:\n{summary}")
        enable_transcoding = getenv("ENABLE_TRANSCODING", "").lower() in ("1", "true", "yes")
        if enable_transcoding:
            print_flush("Transcoding is enabled. Checking if transcoding is needed...")
            final_video_path = maybe_reencode(video_path, tmpdir)
        else:
            print_flush("Transcoding is disabled. Using original video.")
            final_video_path = video_path
        print_flush(f"Final video for posting: {final_video_path}")
        print_flush("Starting Mastodon post...")
        mastodon_url = post_to_mastodon(summary, final_video_path, args.url, mime_type)
        print_flush(f"Mastodon post URL: {mastodon_url}")
        # Temp files are cleaned up automatically

if __name__ == "__main__":
    main()
