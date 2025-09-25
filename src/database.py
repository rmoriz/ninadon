#!/usr/bin/env python3
"""Database management for storing video processing history."""

import json
import os
from datetime import datetime

from .config import Config
from .utils import print_flush


def get_database_path(uploader):
    """Get the database file path for a specific user."""
    # Create user directory if it doesn't exist
    data_root = Config.get_data_root()
    user_dir = os.path.join(data_root, uploader)
    os.makedirs(user_dir, exist_ok=True)
    return os.path.join(user_dir, "database.json")


def get_context_path(uploader):
    """Get the context file path for a specific user."""
    data_root = Config.get_data_root()
    user_dir = os.path.join(data_root, uploader)
    os.makedirs(user_dir, exist_ok=True)
    return os.path.join(user_dir, "context.json")


def load_database(uploader):
    """Load the database for a specific user."""
    db_path = get_database_path(uploader)
    if os.path.exists(db_path):
        try:
            with open(db_path, "r", encoding="utf-8") as f:
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
        with open(db_path, "w", encoding="utf-8") as f:
            json.dump(database, f, indent=2, ensure_ascii=False)
        print_flush(f"Database saved for {uploader}: {len(database)} entries")
    except IOError as e:
        print_flush(f"Warning: Could not save database for {uploader}: {e}")


def add_to_database(
    uploader, title, description, hashtags, platform, transcript, image_analysis=None
):
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
        "transcript": transcript,
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


def load_context(uploader):
    """Load the context summary for a specific user."""
    context_path = get_context_path(uploader)
    if os.path.exists(context_path):
        try:
            with open(context_path, "r", encoding="utf-8") as f:
                context_data = json.load(f)
                return context_data.get("summary", "")
        except (json.JSONDecodeError, IOError) as e:
            print_flush(f"Warning: Could not load context for {uploader}: {e}")
    return None


def save_context(uploader, context_summary, database_entries_count):
    """Save the context summary for a specific user."""
    context_path = get_context_path(uploader)
    context_data = {
        "generated_at": datetime.now().isoformat(),
        "summary": context_summary,
        "based_on_entries": database_entries_count,
    }

    try:
        with open(context_path, "w", encoding="utf-8") as f:
            json.dump(context_data, f, indent=2, ensure_ascii=False)
        print_flush(f"Context summary saved for {uploader}")
    except IOError as e:
        print_flush(f"Warning: Could not save context for {uploader}: {e}")
