#!/usr/bin/env python3
"""AI services for text summarization and context generation."""

import json
import re
from datetime import datetime

import requests

from .config import Config
from .database import load_context, load_database, save_context
from .utils import print_flush


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
        if entry.get("image_recognition"):
            db_content += f"Image Recognition: {entry['image_recognition'][:300]}...\n"
        db_content += "\n---\n\n"

    # Include existing context if available
    if existing_context:
        db_content += f"Previous context summary:\n{existing_context}\n\n---\n\n"

    # Call OpenRouter to summarize the context
    config = Config()
    url = "https://openrouter.ai/api/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "X-Title": "Ninadon",
        "HTTP-Referer": "https://github.com/rmoriz/ninadon",
    }

    data = {
        "model": Config.CONTEXT_MODEL,
        "messages": [{"role": "system", "content": Config.CONTEXT_PROMPT}, {"role": "user", "content": db_content}],
    }

    import sys

    print(f"[OpenRouter CONTEXT REQUEST] URL: {url}", file=sys.stderr)
    print(f"[OpenRouter CONTEXT REQUEST] Model: {Config.CONTEXT_MODEL}", file=sys.stderr)
    print(f"[OpenRouter CONTEXT REQUEST] Database entries: {len(database)}", file=sys.stderr)
    print(f"[OpenRouter CONTEXT REQUEST] Existing context: {'Yes' if existing_context else 'No'}", file=sys.stderr)

    try:
        resp = requests.post(url, headers=headers, json=data)
        print(f"[OpenRouter CONTEXT RESPONSE] Status: {resp.status_code}", file=sys.stderr)

        resp.raise_for_status()
        context_summary = resp.json()["choices"][0]["message"]["content"]

        # Save the context summary
        save_context(uploader, context_summary, len(database))

        print_flush(f"Context summary generated and saved for {uploader}")
        return context_summary

    except requests.exceptions.HTTPError:
        print_flush("Warning: Context generation failed")
        return None
    except Exception:
        print_flush("Warning: Could not generate context")
        return None


def summarize_text(transcript, description, uploader, image_analysis=None, context=None):
    """Generate AI summary of video content using OpenRouter."""
    config = Config()
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "X-Title": "Ninadon",
        "HTTP-Referer": "https://github.com/rmoriz/ninadon",
    }

    merged_transcript = f"{Config.USER_PROMPT}\n\n{transcript}" if Config.USER_PROMPT else transcript

    user_content = f"Account name: {uploader}\nDescription: {description}\nTranscript:\n{merged_transcript}"

    # Add image analysis if available
    if image_analysis:
        user_content += f"\n\nImage Recognition:\n{image_analysis}"

    # Add context if available
    if context:
        user_content += f"\n\nContext:\n{context}"

    data = {
        "model": Config.OPENROUTER_MODEL,
        "messages": [{"role": "system", "content": Config.SYSTEM_PROMPT}, {"role": "user", "content": user_content}],
    }

    import sys

    # Log OpenRouter request (hide API key)
    log_headers = dict(headers)
    if "Authorization" in log_headers:
        log_headers["Authorization"] = "Bearer ***REDACTED***"
    print(f"[OpenRouter REQUEST] URL: {url}", file=sys.stderr)
    print(f"[OpenRouter REQUEST] Headers: {log_headers}", file=sys.stderr)
    print(f"[OpenRouter REQUEST] Payload: {data}", file=sys.stderr)

    resp = requests.post(url, headers=headers, json=data)
    print(f"[OpenRouter RESPONSE] Status: {resp.status_code}", file=sys.stderr)
    print(f"[OpenRouter RESPONSE] Body: {resp.text}", file=sys.stderr)

    try:
        resp.raise_for_status()
    except requests.exceptions.HTTPError:
        if resp.status_code == 404:
            print_flush(
                "ERROR: 404 Not Found from OpenRouter API. This may mean the model name is "
                "invalid or unavailable. Please check the OPENROUTER_MODEL environment variable."
            )
        raise

    summary = resp.json()["choices"][0]["message"]["content"]
    return summary


def extract_summary_and_description(ai_response):
    """Extract both the summary and video description from the AI response."""
    # First try to parse as JSON
    try:
        # Sometimes AI responses have extra text before/after JSON, so extract JSON block
        json_match = re.search(r'\{.*?"summary".*?"video_description".*?\}', ai_response, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
            data = json.loads(json_str)
            summary = data.get("summary", "").strip()
            video_description = data.get("video_description", "").strip()

            # Ensure video description is not longer than 1400 characters
            if len(video_description) > 1400:
                video_description = video_description[:1397] + "..."

            return summary, video_description
    except (json.JSONDecodeError, AttributeError):
        pass

    # Fallback: try the old text-based parsing for backwards compatibility
    # Pattern to find the summary section
    summary_pattern = r"Summary:\s*(.+?)(?=\n\nVideo Description for Visually Impaired:|$)"
    summary_match = re.search(summary_pattern, ai_response, re.DOTALL | re.IGNORECASE)

    # Pattern to find the video description section
    desc_pattern = r"Video Description for Visually Impaired:\s*(.+?)(?:\n\n|$)"
    desc_match = re.search(desc_pattern, ai_response, re.DOTALL | re.IGNORECASE)

    # Extract summary
    if summary_match:
        summary = summary_match.group(1).strip()
    else:
        # Fallback: use everything before "Video Description" or the whole text
        if "Video Description for Visually Impaired:" in ai_response:
            summary = ai_response.split("Video Description for Visually Impaired:")[0].strip()
        else:
            # Last fallback: split the response in half
            lines = ai_response.strip().split("\n")
            mid_point = len(lines) // 2
            summary = "\n".join(lines[:mid_point]).strip()

    # Extract video description
    if desc_match:
        description = desc_match.group(1).strip()
        # Ensure it's not longer than 1400 characters
        if len(description) > 1400:
            description = description[:1397] + "..."
    else:
        # Fallback: use the second half or the summary as description
        lines = ai_response.strip().split("\n")
        mid_point = len(lines) // 2
        if len(lines) > mid_point:
            description = "\n".join(lines[mid_point:]).strip()
        else:
            description = summary

        if len(description) > 1400:
            description = description[:1397] + "..."

    return summary, description
