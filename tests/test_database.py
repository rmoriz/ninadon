#!/usr/bin/env python3
"""Tests for database module."""

import os
import json
import pytest
from datetime import datetime
from unittest.mock import patch, mock_open
from src.database import (
    get_database_path, get_context_path, load_database, save_database,
    add_to_database, load_context, save_context
)


class TestDatabasePaths:
    """Test database path functionality."""
    
    def test_get_database_path(self, tmp_path):
        """Test database path generation."""
        with patch('src.database.Config') as mock_config:
            mock_config.get_data_root.return_value = str(tmp_path)
            
            result = get_database_path("testuser")
            expected = os.path.join(str(tmp_path), "testuser", "database.json")
            assert result == expected
            
            # Check that user directory was created
            user_dir = tmp_path / "testuser"
            assert user_dir.exists()
    
    def test_get_context_path(self, tmp_path):
        """Test context path generation."""
        with patch('src.database.Config') as mock_config:
            mock_config.get_data_root.return_value = str(tmp_path)
            
            result = get_context_path("testuser")
            expected = os.path.join(str(tmp_path), "testuser", "context.json")
            assert result == expected
            
            # Check that user directory was created
            user_dir = tmp_path / "testuser"
            assert user_dir.exists()


class TestLoadDatabase:
    """Test database loading functionality."""
    
    def test_load_database_exists(self, tmp_path):
        """Test loading existing database."""
        user_dir = tmp_path / "testuser"
        user_dir.mkdir()
        db_file = user_dir / "database.json"
        
        test_data = [
            {"title": "Test Video", "platform": "youtube", "date": "2023-01-01T00:00:00"}
        ]
        db_file.write_text(json.dumps(test_data, indent=2), encoding='utf-8')
        
        with patch('src.database.Config') as mock_config:
            mock_config.get_data_root.return_value = str(tmp_path)
            
            result = load_database("testuser")
            assert result == test_data
    
    def test_load_database_not_exists(self, tmp_path):
        """Test loading non-existent database."""
        with patch('src.database.Config') as mock_config:
            mock_config.get_data_root.return_value = str(tmp_path)
            
            result = load_database("testuser")
            assert result == []
    
    def test_load_database_corrupted(self, tmp_path):
        """Test loading corrupted database."""
        user_dir = tmp_path / "testuser"
        user_dir.mkdir()
        db_file = user_dir / "database.json"
        db_file.write_text("invalid json", encoding='utf-8')
        
        with patch('src.database.Config') as mock_config, \
             patch('src.database.print_flush'):
            mock_config.get_data_root.return_value = str(tmp_path)
            
            result = load_database("testuser")
            assert result == []
    
    def test_load_database_io_error(self, tmp_path):
        """Test loading database with IO error."""
        with patch('src.database.Config') as mock_config, \
             patch('src.database.print_flush'), \
             patch('builtins.open', side_effect=IOError("Permission denied")):
            mock_config.get_data_root.return_value = str(tmp_path)
            
            result = load_database("testuser")
            assert result == []


class TestSaveDatabase:
    """Test database saving functionality."""
    
    def test_save_database_success(self, tmp_path):
        """Test successful database saving."""
        test_data = [
            {"title": "Test Video", "platform": "youtube", "date": "2023-01-01T00:00:00"}
        ]
        
        with patch('src.database.Config') as mock_config, \
             patch('src.database.print_flush'):
            mock_config.get_data_root.return_value = str(tmp_path)
            
            save_database("testuser", test_data)
            
            # Verify file was created and contains correct data
            db_path = tmp_path / "testuser" / "database.json"
            assert db_path.exists()
            
            saved_data = json.loads(db_path.read_text(encoding='utf-8'))
            assert saved_data == test_data
    
    def test_save_database_truncate_entries(self, tmp_path):
        """Test database truncation to 25 entries."""
        # Create 30 entries
        test_data = []
        for i in range(30):
            test_data.append({
                "title": f"Video {i}",
                "platform": "youtube",
                "date": f"2023-01-{i+1:02d}T00:00:00"
            })
        
        with patch('src.database.Config') as mock_config, \
             patch('src.database.print_flush'):
            mock_config.get_data_root.return_value = str(tmp_path)
            
            save_database("testuser", test_data)
            
            # Verify only last 25 entries were saved
            db_path = tmp_path / "testuser" / "database.json"
            saved_data = json.loads(db_path.read_text(encoding='utf-8'))
            assert len(saved_data) == 25
            
            # Should contain entries 5-29 (last 25)
            assert saved_data[0]["title"] == "Video 5"
            assert saved_data[-1]["title"] == "Video 29"
    
    def test_save_database_io_error(self, tmp_path):
        """Test saving database with IO error."""
        test_data = [{"title": "Test"}]
        
        with patch('src.database.Config') as mock_config, \
             patch('src.database.print_flush'), \
             patch('builtins.open', side_effect=IOError("Permission denied")):
            mock_config.get_data_root.return_value = str(tmp_path)
            
            # Should not raise exception, just print warning
            save_database("testuser", test_data)


class TestAddToDatabase:
    """Test add to database functionality."""
    
    def test_add_to_database_new_entry(self, tmp_path):
        """Test adding new entry to database."""
        with patch('src.database.Config') as mock_config, \
             patch('src.database.print_flush'), \
             patch('src.database.datetime') as mock_datetime:
            
            mock_config.get_data_root.return_value = str(tmp_path)
            mock_datetime.now.return_value.isoformat.return_value = "2023-01-01T00:00:00"
            
            result = add_to_database(
                "testuser", "Test Video", "Test description", ["#test"], 
                "youtube", "Test transcript", "Test image analysis"
            )
            
            assert len(result) == 1
            entry = result[0]
            assert entry["title"] == "Test Video"
            assert entry["description"] == "Test description"
            assert entry["hashtags"] == ["#test"]
            assert entry["platform"] == "youtube"
            assert entry["transcript"] == "Test transcript"
            assert entry["image_recognition"] == "Test image analysis"
            assert entry["date"] == "2023-01-01T00:00:00"
    
    def test_add_to_database_update_existing(self, tmp_path):
        """Test updating existing entry."""
        # Create initial database with one entry
        user_dir = tmp_path / "testuser"
        user_dir.mkdir()
        db_file = user_dir / "database.json"
        
        initial_data = [{
            "title": "Test Video",
            "platform": "youtube",
            "date": "2023-01-01T00:00:00",
            "description": "Old description",
            "transcript": "Old transcript"
        }]
        db_file.write_text(json.dumps(initial_data), encoding='utf-8')
        
        with patch('src.database.Config') as mock_config, \
             patch('src.database.print_flush'), \
             patch('src.database.datetime') as mock_datetime:
            
            mock_config.get_data_root.return_value = str(tmp_path)
            mock_datetime.now.return_value.isoformat.return_value = "2023-01-02T00:00:00"
            
            result = add_to_database(
                "testuser", "Test Video", "New description", ["#new"], 
                "youtube", "New transcript"
            )
            
            # Should still have only one entry, but updated
            assert len(result) == 1
            entry = result[0]
            assert entry["title"] == "Test Video"
            assert entry["description"] == "New description"
            assert entry["transcript"] == "New transcript"
            assert entry["date"] == "2023-01-02T00:00:00"  # Updated date
    
    def test_add_to_database_without_image_analysis(self, tmp_path):
        """Test adding entry without image analysis."""
        with patch('src.database.Config') as mock_config, \
             patch('src.database.print_flush'), \
             patch('src.database.datetime') as mock_datetime:
            
            mock_config.get_data_root.return_value = str(tmp_path)
            mock_datetime.now.return_value.isoformat.return_value = "2023-01-01T00:00:00"
            
            result = add_to_database(
                "testuser", "Test Video", "Test description", ["#test"], 
                "youtube", "Test transcript"  # No image_analysis parameter
            )
            
            assert len(result) == 1
            entry = result[0]
            assert "image_recognition" not in entry


class TestLoadContext:
    """Test context loading functionality."""
    
    def test_load_context_exists(self, tmp_path):
        """Test loading existing context."""
        user_dir = tmp_path / "testuser"
        user_dir.mkdir()
        context_file = user_dir / "context.json"
        
        context_data = {
            "generated_at": "2023-01-01T00:00:00",
            "summary": "Test context summary",
            "based_on_entries": 5
        }
        context_file.write_text(json.dumps(context_data), encoding='utf-8')
        
        with patch('src.database.Config') as mock_config:
            mock_config.get_data_root.return_value = str(tmp_path)
            
            result = load_context("testuser")
            assert result == "Test context summary"
    
    def test_load_context_not_exists(self, tmp_path):
        """Test loading non-existent context."""
        with patch('src.database.Config') as mock_config:
            mock_config.get_data_root.return_value = str(tmp_path)
            
            result = load_context("testuser")
            assert result is None
    
    def test_load_context_corrupted(self, tmp_path):
        """Test loading corrupted context."""
        user_dir = tmp_path / "testuser"
        user_dir.mkdir()
        context_file = user_dir / "context.json"
        context_file.write_text("invalid json", encoding='utf-8')
        
        with patch('src.database.Config') as mock_config, \
             patch('src.database.print_flush'):
            mock_config.get_data_root.return_value = str(tmp_path)
            
            result = load_context("testuser")
            assert result is None
    
    def test_load_context_missing_summary(self, tmp_path):
        """Test loading context without summary field."""
        user_dir = tmp_path / "testuser"
        user_dir.mkdir()
        context_file = user_dir / "context.json"
        
        context_data = {
            "generated_at": "2023-01-01T00:00:00",
            "based_on_entries": 5
            # Missing "summary" field
        }
        context_file.write_text(json.dumps(context_data), encoding='utf-8')
        
        with patch('src.database.Config') as mock_config:
            mock_config.get_data_root.return_value = str(tmp_path)
            
            result = load_context("testuser")
            assert result == ""  # Should return empty string for missing summary


class TestSaveContext:
    """Test context saving functionality."""
    
    def test_save_context_success(self, tmp_path):
        """Test successful context saving."""
        with patch('src.database.Config') as mock_config, \
             patch('src.database.print_flush'), \
             patch('src.database.datetime') as mock_datetime:
            
            mock_config.get_data_root.return_value = str(tmp_path)
            mock_datetime.now.return_value.isoformat.return_value = "2023-01-01T00:00:00"
            
            save_context("testuser", "Test context summary", 10)
            
            # Verify file was created and contains correct data
            context_path = tmp_path / "testuser" / "context.json"
            assert context_path.exists()
            
            saved_data = json.loads(context_path.read_text(encoding='utf-8'))
            assert saved_data["summary"] == "Test context summary"
            assert saved_data["generated_at"] == "2023-01-01T00:00:00"
            assert saved_data["based_on_entries"] == 10
    
    def test_save_context_io_error(self, tmp_path):
        """Test saving context with IO error."""
        with patch('src.database.Config') as mock_config, \
             patch('src.database.print_flush'), \
             patch('src.database.datetime') as mock_datetime, \
             patch('builtins.open', side_effect=IOError("Permission denied")):
            
            mock_config.get_data_root.return_value = str(tmp_path)
            mock_datetime.now.return_value.isoformat.return_value = "2023-01-01T00:00:00"
            
            # Should not raise exception, just print warning
            save_context("testuser", "Test context summary", 10)


class TestDatabaseIntegration:
    """Test database integration scenarios."""
    
    def test_full_workflow(self, tmp_path):
        """Test complete database workflow."""
        with patch('src.database.Config') as mock_config, \
             patch('src.database.print_flush'), \
             patch('src.database.datetime') as mock_datetime:
            
            mock_config.get_data_root.return_value = str(tmp_path)
            mock_datetime.now.return_value.isoformat.return_value = "2023-01-01T00:00:00"
            
            # Add first entry
            add_to_database("testuser", "Video 1", "Description 1", ["#test"], "youtube", "Transcript 1")
            
            # Add second entry
            mock_datetime.now.return_value.isoformat.return_value = "2023-01-02T00:00:00"
            add_to_database("testuser", "Video 2", "Description 2", ["#cool"], "tiktok", "Transcript 2")
            
            # Load database and verify
            database = load_database("testuser")
            assert len(database) == 2
            assert database[0]["title"] == "Video 1"
            assert database[1]["title"] == "Video 2"
            
            # Save context
            save_context("testuser", "User creates diverse content", 2)
            
            # Load context and verify
            context = load_context("testuser")
            assert context == "User creates diverse content"
    
    def test_user_isolation(self, tmp_path):
        """Test that different users have isolated data."""
        with patch('src.database.Config') as mock_config, \
             patch('src.database.print_flush'), \
             patch('src.database.datetime') as mock_datetime:
            
            mock_config.get_data_root.return_value = str(tmp_path)
            mock_datetime.now.return_value.isoformat.return_value = "2023-01-01T00:00:00"
            
            # Add data for user1
            add_to_database("user1", "User1 Video", "Description", ["#user1"], "youtube", "Transcript")
            save_context("user1", "User1 context", 1)
            
            # Add data for user2
            add_to_database("user2", "User2 Video", "Description", ["#user2"], "tiktok", "Transcript")
            save_context("user2", "User2 context", 1)
            
            # Verify isolation
            user1_db = load_database("user1")
            user2_db = load_database("user2")
            
            assert len(user1_db) == 1
            assert len(user2_db) == 1
            assert user1_db[0]["title"] == "User1 Video"
            assert user2_db[0]["title"] == "User2 Video"
            
            user1_context = load_context("user1")
            user2_context = load_context("user2")
            
            assert user1_context == "User1 context"
            assert user2_context == "User2 context"