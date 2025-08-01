"""Tests for bulk import tool with progress notifications."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, mock_open, patch

import pytest
from fastmcp import Context
from pydantic import ValidationError

from tools.bulk_import import (
    BulkImportInput,
    bulk_import_books_handler,
    import_books_from_file,
)


class TestBulkImportInput:
    """Test input validation for bulk import tool."""
    
    def test_valid_input(self):
        """Test valid input parameters."""
        input_data = {
            "file_path": "/tmp/books.csv",
            "batch_size": 100
        }
        params = BulkImportInput.model_validate(input_data)
        assert params.file_path == "/tmp/books.csv"
        assert params.batch_size == 100
    
    def test_default_batch_size(self):
        """Test default batch size is applied."""
        input_data = {"file_path": "/tmp/books.json"}
        params = BulkImportInput.model_validate(input_data)
        assert params.batch_size == 50
    
    def test_batch_size_validation(self):
        """Test batch size constraints."""
        # Too small
        with pytest.raises(ValidationError):
            BulkImportInput.model_validate({
                "file_path": "/tmp/books.csv",
                "batch_size": 0
            })
        
        # Too large
        with pytest.raises(ValidationError):
            BulkImportInput.model_validate({
                "file_path": "/tmp/books.csv",
                "batch_size": 1001
            })
    
    def test_empty_file_path(self):
        """Test that empty file path is rejected."""
        with pytest.raises(ValidationError):
            BulkImportInput.model_validate({"file_path": ""})


@pytest.mark.asyncio
class TestImportBooksFromFile:
    """Test the core import functionality with progress reporting."""
    
    async def test_csv_import_with_progress(self, tmp_path):
        """Test importing books from CSV with progress notifications."""
        # Create test CSV file
        csv_content = """isbn,title,author_name,genre,publication_year,available_copies
978-0-123456-78-9,Test Book 1,Author One,Fiction,2023,5
978-0-123456-79-6,Test Book 2,Author Two,Non-Fiction,2022,3"""
        
        csv_file = tmp_path / "test_books.csv"
        csv_file.write_text(csv_content)
        
        # Mock context and repository
        ctx = AsyncMock(spec=Context)
        
        with patch('tools.bulk_import.session_scope') as mock_session_scope:
            mock_session = MagicMock()
            mock_session_scope.return_value.__enter__.return_value = mock_session
            
            # Mock database queries
            mock_session.query.return_value.filter_by.return_value.first.return_value = None
            mock_session.add = MagicMock()
            mock_session.flush = MagicMock()
            mock_session.commit = MagicMock()
            
            result = await import_books_from_file(
                str(csv_file),
                ctx,
                batch_size=2
            )
        
        # Verify progress reporting
        assert ctx.report_progress.call_count >= 2  # At least once per book
        
        # Check first progress call
        first_call = ctx.report_progress.call_args_list[0]
        assert first_call[1]['progress'] == 1
        assert first_call[1]['total'] == 2
        assert 'Importing book 1/2' in first_call[1]['message']
        
        # Verify result
        assert result['total_books'] == 2
        assert result['successful_imports'] == 2
        assert result['failed_imports'] == 0
        assert result['success_rate'] == '100.0%'
    
    async def test_json_import_with_progress(self, tmp_path):
        """Test importing books from JSON with progress notifications."""
        # Create test JSON file
        json_data = [
            {
                "isbn": "978-0-123456-78-9",
                "title": "JSON Book 1",
                "author_name": "JSON Author",
                "genre": "Technology",
                "publication_year": 2023,
                "available_copies": 4
            }
        ]
        
        json_file = tmp_path / "test_books.json"
        json_file.write_text(json.dumps(json_data))
        
        # Mock context
        ctx = AsyncMock(spec=Context)
        
        with patch('tools.bulk_import.session_scope') as mock_session_scope:
            mock_session = MagicMock()
            mock_session_scope.return_value.__enter__.return_value = mock_session
            
            # Mock database queries
            mock_session.query.return_value.filter_by.return_value.first.return_value = None
            mock_session.add = MagicMock()
            mock_session.flush = MagicMock()
            mock_session.commit = MagicMock()
            
            result = await import_books_from_file(
                str(json_file),
                ctx,
                batch_size=10
            )
        
        # Verify progress reporting
        progress_calls = [
            call for call in ctx.report_progress.call_args_list
            if 'Importing book' in call[1].get('message', '')
        ]
        assert len(progress_calls) >= 1
        
        # Verify result
        assert result['total_books'] == 1
        assert result['successful_imports'] == 1
    
    async def test_import_with_validation_errors(self, tmp_path):
        """Test handling of validation errors during import."""
        # Create CSV with invalid data
        csv_content = """isbn,title,author_name,genre,publication_year,available_copies
,Missing ISBN,Author,Fiction,2023,5
978-0-123456-78-9,Valid Book,Author,Fiction,2023,3"""
        
        csv_file = tmp_path / "invalid_books.csv"
        csv_file.write_text(csv_content)
        
        # Mock context
        ctx = AsyncMock(spec=Context)
        
        with patch('tools.bulk_import.session_scope') as mock_session_scope:
            mock_session = MagicMock()
            mock_session_scope.return_value.__enter__.return_value = mock_session
            
            # Mock database queries
            mock_session.query.return_value.filter_by.return_value.first.return_value = None
            mock_session.add = MagicMock()
            mock_session.flush = MagicMock()
            mock_session.commit = MagicMock()
            
            result = await import_books_from_file(
                str(csv_file),
                ctx,
                batch_size=10
            )
        
        # Should have one warning for the invalid book
        print(f"Warning calls: {ctx.warning.call_args_list}")
        warning_calls = [
            call for call in ctx.warning.call_args_list
            if 'Validation error' in str(call) or 'ISBN is required' in str(call)
        ]
        assert len(warning_calls) == 1
        
        # Verify result
        assert result['total_books'] == 2
        assert result['successful_imports'] == 1
        assert result['failed_imports'] == 1
        assert len(result['errors']) == 1
    
    async def test_file_not_found(self):
        """Test handling of non-existent file."""
        ctx = AsyncMock(spec=Context)
        
        with pytest.raises(FileNotFoundError, match="Import file not found"):
            await import_books_from_file(
                "/nonexistent/file.csv",
                ctx
            )
    
    async def test_unsupported_file_type(self, tmp_path):
        """Test rejection of unsupported file types."""
        txt_file = tmp_path / "books.txt"
        txt_file.write_text("Some text")
        
        ctx = AsyncMock(spec=Context)
        
        with pytest.raises(ValueError, match="Unsupported file type"):
            await import_books_from_file(
                str(txt_file),
                ctx
            )


@pytest.mark.asyncio
class TestBulkImportBooksHandler:
    """Test the MCP tool handler."""
    
    async def test_successful_import(self, tmp_path):
        """Test successful import through handler."""
        # Create test file
        csv_file = tmp_path / "books.csv"
        csv_file.write_text("isbn,title,author_name,genre,publication_year,available_copies\n"
                          "978-0-123456-78-9,Test Book,Author,Fiction,2023,5")
        
        ctx = AsyncMock(spec=Context)
        
        with patch('tools.bulk_import.import_books_from_file') as mock_import:
            mock_import.return_value = {
                'total_books': 1,
                'successful_imports': 1,
                'failed_imports': 0,
                'success_rate': '100.0%',
                'errors': []
            }
            
            result = await bulk_import_books_handler(
                {"file_path": str(csv_file), "batch_size": 50},
                ctx
            )
        
        assert not result.get('isError')
        assert 'Import completed: 1/1 books imported successfully' in result['content'][0]['text']
        assert result['data']['successful_imports'] == 1
    
    async def test_invalid_parameters(self):
        """Test handler with invalid parameters."""
        ctx = AsyncMock(spec=Context)
        
        result = await bulk_import_books_handler(
            {"file_path": "", "batch_size": 50},
            ctx
        )
        
        assert result['isError']
        assert 'Invalid import parameters' in result['content'][0]['text']
    
    async def test_file_not_found_error(self):
        """Test handler with non-existent file."""
        ctx = AsyncMock(spec=Context)
        
        with patch('tools.bulk_import.import_books_from_file') as mock_import:
            mock_import.side_effect = FileNotFoundError("File not found")
            
            result = await bulk_import_books_handler(
                {"file_path": "/nonexistent/file.csv"},
                ctx
            )
        
        assert result['isError']
        assert 'File not found' in result['content'][0]['text']
    
    async def test_import_with_errors(self):
        """Test handler when import has errors."""
        ctx = AsyncMock(spec=Context)
        
        with patch('tools.bulk_import.import_books_from_file') as mock_import:
            mock_import.return_value = {
                'total_books': 10,
                'successful_imports': 7,
                'failed_imports': 3,
                'success_rate': '70.0%',
                'errors': [
                    'Book 1: Validation error',
                    'Book 5: Database error',
                    'Book 8: Duplicate ISBN'
                ]
            }
            
            result = await bulk_import_books_handler(
                {"file_path": "/tmp/books.csv"},
                ctx
            )
        
        assert not result.get('isError')
        content = result['content'][0]['text']
        assert '7/10 books imported successfully' in content
        assert '3 imports failed' in content
        assert 'Book 1: Validation error' in content