#!/usr/bin/env python3
import argparse
import tempfile
import os
import yt_dlp
import whisper
import requests


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
        # TODO: Post, cleanup

if __name__ == "__main__":
    main()
