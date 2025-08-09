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
import base64
import json
from datetime import datetime
import re

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
    title = info.get('title', '')
    description = info.get('description', '')
    uploader = info.get('uploader', info.get('channel', info.get('author', '')))
    
    # Extract hashtags from title and description
    hashtags = []
    text_to_search = f"{title} {description}"
    hashtag_matches = re.findall(r'#\w+', text_to_search)
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
    if 'requested_downloads' in info and info['requested_downloads']:
        mime_type = info['requested_downloads'][0].get('mime_type')
    if not mime_type:
        mime_type = info.get('mime_type')
    
    return filepath, title, description, uploader, hashtags, platform, mime_type

def transcribe_video(video_path):
    model = whisper.load_model("base")
    result = model.transcribe(video_path)
    return result["text"]

def get_video_duration(video_path):
    """Get video duration in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
        "-of", "csv=p=0", video_path
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
        duration * 0.5,   # 50%
        duration * 0.75,  # 75%
        max(duration - 0.5, 0.5)  # End (but not before 0.5s)
    ]
    
    image_paths = []
    for i, timestamp in enumerate(timestamps):
        image_path = os.path.join(tmpdir, f"frame_{i:02d}.jpg")
        cmd = [
            "ffmpeg", "-ss", str(timestamp), "-i", video_path,
            "-vframes", "1", "-q:v", "5", "-y", image_path
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        image_paths.append(image_path)
        print_flush(f"Extracted frame at {timestamp:.1f}s: {image_path}")
    
    return image_paths

def encode_image_to_base64(image_path):
    """Encode image to base64 for API transmission."""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def analyze_images_with_openrouter(image_paths):
    """Analyze images using OpenRouter with Gemini model."""
    api_key = getenv("OPENROUTER_API_KEY", required=True)
    model = getenv("ENHANCE_MODEL", "google/gemini-2.5-flash-lite")
    url = "https://openrouter.ai/api/v1/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "Ninadon",
        "HTTP-Referer": "https://github.com/rmoriz/ninadon"
    }
    
    # Prepare image content for the API
    content = [
        {
            "type": "text",
            "text": "Analyze these photos from a tiktok clip, make a connection between the photos"
        }
    ]
    
    for image_path in image_paths:
        base64_image = encode_image_to_base64(image_path)
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{base64_image}"
            }
        })
    
    data = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": content
            }
        ]
    }
    
    import sys
    # Log OpenRouter request (hide API key)
    log_headers = dict(headers)
    if 'Authorization' in log_headers:
        log_headers['Authorization'] = 'Bearer ***REDACTED***'
    print(f"[OpenRouter IMAGE REQUEST] URL: {url}", file=sys.stderr)
    print(f"[OpenRouter IMAGE REQUEST] Headers: {log_headers}", file=sys.stderr)
    print(f"[OpenRouter IMAGE REQUEST] Model: {model}", file=sys.stderr)
    print(f"[OpenRouter IMAGE REQUEST] Images: {len(image_paths)}", file=sys.stderr)
    
    resp = requests.post(url, headers=headers, json=data)
    print(f"[OpenRouter IMAGE RESPONSE] Status: {resp.status_code}", file=sys.stderr)
    print(f"[OpenRouter IMAGE RESPONSE] Body: {resp.text}", file=sys.stderr)
    
    try:
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        if resp.status_code == 404:
            print_flush("ERROR: 404 Not Found from OpenRouter API for image analysis. This may mean the model name is invalid or unavailable. Please check the ENHANCE_MODEL environment variable.")
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
    data_path = getenv("DATA_PATH", "/app/data")
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
            with open(db_path, 'r', encoding='utf-8') as f:
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
        with open(db_path, 'w', encoding='utf-8') as f:
            json.dump(database, f, indent=2, ensure_ascii=False)
        print_flush(f"Database saved for {uploader}: {len(database)} entries")
    except IOError as e:
        print_flush(f"Warning: Could not save database for {uploader}: {e}")

def add_to_database(uploader, title, description, hashtags, platform, transcript, image_analysis=None):
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
        "transcript": transcript
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
        print_flush(f"No database entries found for {uploader}, skipping context generation")
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
        db_content += f"Transcript: {entry['transcript'][:500]}...\n"  # Limit transcript length
        if entry.get('image_recognition'):
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
        "HTTP-Referer": "https://github.com/rmoriz/ninadon"
    }
    
    system_prompt = "Analyze the following video history and create a concise context summary that captures the user's content themes, interests, and patterns. Focus on recurring topics, style, and audience. If a previous context summary is provided, build upon it and update it with new insights from the recent videos, maintaining continuity while incorporating new patterns or changes."
    
    data = {
        "model": context_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": db_content}
        ]
    }
    
    import sys
    print(f"[OpenRouter CONTEXT REQUEST] URL: {url}", file=sys.stderr)
    print(f"[OpenRouter CONTEXT REQUEST] Model: {context_model}", file=sys.stderr)
    print(f"[OpenRouter CONTEXT REQUEST] Database entries: {len(database)}", file=sys.stderr)
    print(f"[OpenRouter CONTEXT REQUEST] Existing context: {'Yes' if existing_context else 'No'}", file=sys.stderr)
    
    try:
        resp = requests.post(url, headers=headers, json=data)
        print(f"[OpenRouter CONTEXT RESPONSE] Status: {resp.status_code}", file=sys.stderr)
        
        resp.raise_for_status()
        context_summary = resp.json()["choices"][0]["message"]["content"]
        
        # Save the context summary
        context_path = get_context_path(uploader)
        context_data = {
            "generated_at": datetime.now().isoformat(),
            "summary": context_summary,
            "based_on_entries": len(database)
        }
        
        with open(context_path, 'w', encoding='utf-8') as f:
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
            with open(context_path, 'r', encoding='utf-8') as f:
                context_data = json.load(f)
                return context_data.get('summary', '')
        except (json.JSONDecodeError, IOError) as e:
            print_flush(f"Warning: Could not load context for {uploader}: {e}")
    return None

def summarize_text(transcript, description, uploader, image_analysis=None, context=None):
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
            {"role": "user", "content": user_content}
        ]
    }
    import sys
    # Log OpenRouter request (hide API key)
    log_headers = dict(headers)
    if 'Authorization' in log_headers:
        log_headers['Authorization'] = 'Bearer ***REDACTED***'
    print(f"[OpenRouter REQUEST] URL: {url}", file=sys.stderr)
    print(f"[OpenRouter REQUEST] Headers: {log_headers}", file=sys.stderr)
    print(f"[OpenRouter REQUEST] Payload: {data}", file=sys.stderr)
    resp = requests.post(url, headers=headers, json=data)
    print(f"[OpenRouter RESPONSE] Status: {resp.status_code}", file=sys.stderr)
    print(f"[OpenRouter RESPONSE] Body: {resp.text}", file=sys.stderr)
    try:
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        if resp.status_code == 404:
            print_flush("ERROR: 404 Not Found from OpenRouter API. This may mean the model name is invalid or unavailable. Please check the OPENROUTER_MODEL environment variable and use a valid model name, such as 'openai/gpt-4o'.")
        raise
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
    parser.add_argument('--dry', action='store_true', help='Perform dry run without posting to Mastodon')
    parser.add_argument('--enhance', action='store_true', help='Extract still images and analyze them for enhanced summarization')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmpdir:
        import sys
        print_flush(f"Working in temp dir: {tmpdir}")
        print_flush("Starting download...")
        video_path, title, description, uploader, hashtags, platform, mime_type = download_video(args.url, tmpdir)
        print_flush(f"Downloaded video to: {video_path}")
        print_flush(f"Title: {title}")
        print_flush(f"Uploader: {uploader}")
        print_flush(f"Platform: {platform}")
        print_flush(f"Description: {description}")
        print_flush(f"Hashtags: {hashtags}")
        print_flush("Starting transcription...")
        transcript = transcribe_video(video_path)
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
        add_to_database(uploader, title, description, hashtags, platform, transcript, image_analysis)
        
        # Generate context summary from database
        print_flush("Generating context summary...")
        context = generate_context_summary(uploader)
        if context:
            print_flush(f"Context:\n{context}")
        else:
            print_flush("No context available")
        
        print_flush("Starting summarization...")
        summary = summarize_text(transcript, description, uploader, image_analysis, context)
        print_flush(f"Summary:\n{summary}")
        enable_transcoding = getenv("ENABLE_TRANSCODING", "").lower() in ("1", "true", "yes")
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
        else:
            print_flush("Starting Mastodon post...")
            mastodon_url = post_to_mastodon(summary, final_video_path, args.url, mime_type)
            print_flush(f"Mastodon post URL: {mastodon_url}")
        # Temp files are cleaned up automatically

if __name__ == "__main__":
    main()
