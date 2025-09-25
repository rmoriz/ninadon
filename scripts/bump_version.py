#!/usr/bin/env python3
"""
Version management script for Ninadon.
Updates version in both src/__init__.py and VERSION files.
"""

import re
import sys
from pathlib import Path


def get_current_version():
    """Get current version from src/__init__.py"""
    init_file = Path("src/__init__.py")
    if not init_file.exists():
        print("Error: src/__init__.py not found")
        return None
    
    content = init_file.read_text()
    match = re.search(r'__version__ = "([^"]+)"', content)
    if match:
        return match.group(1)
    return None


def update_version(new_version):
    """Update version in both files"""
    # Update src/__init__.py
    init_file = Path("src/__init__.py")
    content = init_file.read_text()
    content = re.sub(r'__version__ = "[^"]+"', f'__version__ = "{new_version}"', content)
    init_file.write_text(content)
    
    # Update VERSION file
    version_file = Path("VERSION")
    version_file.write_text(new_version)
    
    print(f"✅ Updated version to {new_version}")


def bump_version(version_type):
    """Bump version based on type (major, minor, patch)"""
    current = get_current_version()
    if not current:
        print("Error: Could not get current version")
        return
    
    try:
        major, minor, patch = map(int, current.split('.'))
    except ValueError:
        print(f"Error: Invalid version format: {current}")
        return
    
    if version_type == "major":
        major += 1
        minor = 0
        patch = 0
    elif version_type == "minor":
        minor += 1
        patch = 0
    elif version_type == "patch":
        patch += 1
    else:
        print("Error: Version type must be 'major', 'minor', or 'patch'")
        return
    
    new_version = f"{major}.{minor}.{patch}"
    update_version(new_version)


def main():
    if len(sys.argv) < 2:
        current = get_current_version()
        print(f"Current version: {current}")
        print("\nUsage:")
        print("  python scripts/bump_version.py major|minor|patch")
        print("  python scripts/bump_version.py set <version>")
        return
    
    command = sys.argv[1]
    
    if command in ["major", "minor", "patch"]:
        bump_version(command)
    elif command == "set" and len(sys.argv) > 2:
        new_version = sys.argv[2]
        update_version(new_version)
    else:
        print("Invalid command. Use 'major', 'minor', 'patch', or 'set <version>'")


if __name__ == "__main__":
    main()