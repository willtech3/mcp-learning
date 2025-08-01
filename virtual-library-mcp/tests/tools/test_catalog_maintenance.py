"""Tests for catalog maintenance tool with progress notifications."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Context
from sqlalchemy import func

from tools.catalog_maintenance import (
    regenerate_catalog,
    regenerate_catalog_handler,
    _verify_data_integrity,
    _rebuild_search_indexes,
    _update_circulation_stats,
    _generate_recommendations_cache,
)


@pytest.mark.asyncio
class TestDataIntegrityCheck:
    """Test data integrity verification stage."""
    
    async def test_verify_data_integrity_clean(self):
        """Test integrity check with no issues."""
        ctx = AsyncMock(spec=Context)
        
        with patch('tools.catalog_maintenance.session_scope') as mock_session_scope:
            mock_session = MagicMock()
            mock_session_scope.return_value.__enter__.return_value = mock_session
            
            # Mock clean data
            mock_query = MagicMock()
            mock_session.query.return_value = mock_query
            mock_query.scalar.side_effect = [
                100,  # Total books
            ]
            mock_query.filter.return_value.scalar.side_effect = [
                0,    # Orphaned books
                0     # Invalid circulations
            ]
            
            result = await _verify_data_integrity(ctx, 0, 20)
        
        # Verify progress reporting
        progress_calls = ctx.report_progress.call_args_list
        assert len(progress_calls) >= 3
        
        # Check progress values
        assert progress_calls[-1][1]['progress'] == 20
        assert progress_calls[-1][1]['total'] == 100
        
        # Verify result
        assert result['books_checked'] == 100
        assert result['orphaned_books'] == 0
        assert result['invalid_circulations'] == 0
        
        # No warnings should be issued
        assert ctx.warning.call_count == 0
    
    async def test_verify_data_integrity_with_issues(self):
        """Test integrity check with data issues."""
        ctx = AsyncMock(spec=Context)
        
        with patch('tools.catalog_maintenance.session_scope') as mock_session_scope:
            mock_session = MagicMock()
            mock_session_scope.return_value.__enter__.return_value = mock_session
            
            # Mock data with issues
            mock_query = MagicMock()
            mock_session.query.return_value = mock_query
            mock_query.scalar.side_effect = [
                100,  # Total books
            ]
            mock_query.filter.return_value.scalar.side_effect = [
                5,    # Orphaned books
                3     # Invalid circulations
            ]
            
            result = await _verify_data_integrity(ctx, 0, 20)
        
        # Verify warnings were issued
        assert ctx.warning.call_count == 2
        warning_messages = [call[0][0] for call in ctx.warning.call_args_list]
        assert any('5 books without authors' in msg for msg in warning_messages)
        assert any('3 invalid circulation records' in msg for msg in warning_messages)
        
        # Verify result
        assert result['orphaned_books'] == 5
        assert result['invalid_circulations'] == 3


@pytest.mark.asyncio
class TestSearchIndexRebuilding:
    """Test search index rebuilding stage."""
    
    async def test_rebuild_search_indexes(self):
        """Test rebuilding search indexes with progress."""
        ctx = AsyncMock(spec=Context)
        
        with patch('tools.catalog_maintenance.session_scope') as mock_session_scope:
            mock_session = MagicMock()
            mock_session_scope.return_value.__enter__.return_value = mock_session
            
            # Mock counts
            mock_session.query().scalar.side_effect = [
                250,  # Total books
                30,   # Total authors
                15    # Unique genres
            ]
            
            result = await _rebuild_search_indexes(ctx, 20, 50)
        
        # Verify progress reporting for batch processing
        progress_calls = ctx.report_progress.call_args_list
        batch_progress_calls = [
            call for call in progress_calls
            if 'Indexing books' in call[1].get('message', '')
        ]
        assert len(batch_progress_calls) >= 2  # At least 2 batches for 250 books
        
        # Verify final progress
        assert progress_calls[-1][1]['progress'] == 50
        
        # Verify info logging
        info_calls = ctx.info.call_args_list
        assert any('Indexed 250 books' in str(call) for call in info_calls)
        
        # Verify result
        assert result['books_indexed'] == 250
        assert result['authors_indexed'] == 30
        assert result['genres_indexed'] == 15


@pytest.mark.asyncio
class TestCirculationStatsUpdate:
    """Test circulation statistics update stage."""
    
    async def test_update_circulation_stats(self):
        """Test updating circulation statistics."""
        ctx = AsyncMock(spec=Context)
        
        with patch('tools.catalog_maintenance.session_scope') as mock_session_scope:
            mock_session = MagicMock()
            mock_repo = MagicMock()
            mock_session_scope.return_value.__enter__.return_value = mock_session
            
            # Mock circulation data
            mock_repo.get_active_loans.return_value = ['loan1', 'loan2', 'loan3']
            mock_repo.get_overdue_loans.return_value = ['loan2']
            mock_session.query().scalar.return_value = 500  # Total circulations
            
            with patch('tools.catalog_maintenance.CirculationRepository', return_value=mock_repo):
                result = await _update_circulation_stats(ctx, 50, 80)
        
        # Verify progress reporting
        progress_calls = ctx.report_progress.call_args_list
        assert progress_calls[-1][1]['progress'] == 80
        
        # Verify warning for overdue loans
        assert ctx.warning.call_count == 1
        assert 'Found 1 overdue loans' in ctx.warning.call_args[0][0]
        
        # Verify result
        assert result['active_loans'] == 3
        assert result['overdue_loans'] == 1
        assert result['total_circulations'] == 500
        assert result['popular_books_updated'] == 50


@pytest.mark.asyncio
class TestRecommendationsCache:
    """Test recommendations cache generation stage."""
    
    async def test_generate_recommendations_cache(self):
        """Test generating recommendations cache with progress."""
        ctx = AsyncMock(spec=Context)
        
        with patch('tools.catalog_maintenance.session_scope') as mock_session_scope:
            mock_session = MagicMock()
            mock_patron_repo = MagicMock()
            mock_session_scope.return_value.__enter__.return_value = mock_session
            
            # Mock patron data
            mock_patrons = MagicMock()
            mock_patrons.items = [f'patron{i}' for i in range(25)]
            mock_patron_repo.list.return_value = mock_patrons
            
            with patch('tools.catalog_maintenance.PatronRepository', return_value=mock_patron_repo):
                result = await _generate_recommendations_cache(ctx, 80, 100)
        
        # Verify progress reporting for batches
        progress_calls = ctx.report_progress.call_args_list
        batch_progress_calls = [
            call for call in progress_calls
            if 'Generating recommendations' in call[1].get('message', '')
        ]
        assert len(batch_progress_calls) >= 2  # At least 2 batches for 25 patrons
        
        # Verify final progress
        assert progress_calls[-1][1]['progress'] == 100
        assert 'Recommendations cache generated' in progress_calls[-1][1]['message']
        
        # Verify info logging
        assert ctx.info.call_count == 1
        assert 'Generated 125 recommendations for 25 patrons' in ctx.info.call_args[0][0]
        
        # Verify result
        assert result['patrons_processed'] == 25
        assert result['recommendations_generated'] == 125  # 5 per patron
        assert result['cache_size_kb'] == 250  # 2KB per recommendation


@pytest.mark.asyncio
class TestRegenerateCatalog:
    """Test the main regenerate catalog function."""
    
    async def test_regenerate_catalog_full_flow(self):
        """Test full catalog regeneration with all stages."""
        ctx = AsyncMock(spec=Context)
        
        # Mock all stage functions
        with patch('tools.catalog_maintenance._verify_data_integrity') as mock_verify:
            mock_verify.return_value = {
                'books_checked': 100,
                'orphaned_books': 0,
                'invalid_circulations': 0
            }
            
            with patch('tools.catalog_maintenance._rebuild_search_indexes') as mock_rebuild:
                mock_rebuild.return_value = {
                    'books_indexed': 100,
                    'authors_indexed': 20,
                    'genres_indexed': 10
                }
                
                with patch('tools.catalog_maintenance._update_circulation_stats') as mock_stats:
                    mock_stats.return_value = {
                        'active_loans': 15,
                        'overdue_loans': 2,
                        'total_circulations': 200,
                        'popular_books_updated': 50
                    }
                    
                    with patch('tools.catalog_maintenance._generate_recommendations_cache') as mock_cache:
                        mock_cache.return_value = {
                            'patrons_processed': 30,
                            'recommendations_generated': 150,
                            'cache_size_kb': 300
                        }
                        
                        result = await regenerate_catalog(ctx)
        
        # Verify all stages were called with correct progress ranges
        mock_verify.assert_called_once_with(ctx, 0, 20)
        mock_rebuild.assert_called_once_with(ctx, 20, 50)
        mock_stats.assert_called_once_with(ctx, 50, 80)
        mock_cache.assert_called_once_with(ctx, 80, 100)
        
        # Verify stage announcements
        info_calls = [call[0][0] for call in ctx.info.call_args_list]
        assert 'Starting catalog regeneration' in info_calls
        assert 'Stage 1: Verifying data integrity' in info_calls
        assert 'Stage 2: Rebuilding search indexes' in info_calls
        assert 'Stage 3: Updating circulation statistics' in info_calls
        assert 'Stage 4: Generating recommendations cache' in info_calls
        assert 'Catalog regeneration completed successfully' in info_calls
        
        # Verify final progress
        final_progress = ctx.report_progress.call_args_list[-1]
        assert final_progress[1]['progress'] == 100
        assert final_progress[1]['total'] == 100
        assert 'Catalog regeneration complete' in final_progress[1]['message']
        
        # Verify result structure
        assert result['status'] == 'completed'
        assert 'integrity_check' in result
        assert 'search_indexes' in result
        assert 'circulation_stats' in result
        assert 'recommendations_cache' in result


@pytest.mark.asyncio
class TestRegenerateCatalogHandler:
    """Test the MCP tool handler."""
    
    async def test_successful_regeneration(self):
        """Test successful catalog regeneration through handler."""
        ctx = AsyncMock(spec=Context)
        
        with patch('tools.catalog_maintenance.regenerate_catalog') as mock_regenerate:
            mock_regenerate.return_value = {
                'status': 'completed',
                'integrity_check': {
                    'books_checked': 100,
                    'orphaned_books': 0,
                    'invalid_circulations': 0
                },
                'search_indexes': {
                    'books_indexed': 100,
                    'authors_indexed': 20,
                    'genres_indexed': 10
                },
                'circulation_stats': {
                    'active_loans': 15,
                    'overdue_loans': 2,
                    'total_circulations': 200,
                    'popular_books_updated': 50
                },
                'recommendations_cache': {
                    'patrons_processed': 30,
                    'recommendations_generated': 150,
                    'cache_size_kb': 300
                }
            }
            
            result = await regenerate_catalog_handler({}, ctx)
        
        assert not result.get('isError')
        content = result['content'][0]['text']
        
        # Verify summary content
        assert 'Catalog regeneration completed successfully!' in content
        assert '✓ Data Integrity: 100 books checked' in content
        assert '✓ Search Indexes: 100 books, 20 authors, 10 genres indexed' in content
        assert '✓ Circulation Stats: 15 active loans, 2 overdue' in content
        assert '✓ Recommendations: Generated for 30 patrons' in content
        
        # Verify data is included
        assert result['data']['status'] == 'completed'
    
    async def test_regeneration_with_warnings(self):
        """Test handler output when integrity issues are found."""
        ctx = AsyncMock(spec=Context)
        
        with patch('tools.catalog_maintenance.regenerate_catalog') as mock_regenerate:
            mock_regenerate.return_value = {
                'status': 'completed',
                'integrity_check': {
                    'books_checked': 100,
                    'orphaned_books': 5,
                    'invalid_circulations': 3
                },
                'search_indexes': {
                    'books_indexed': 100,
                    'authors_indexed': 20,
                    'genres_indexed': 10
                },
                'circulation_stats': {
                    'active_loans': 15,
                    'overdue_loans': 0,
                    'total_circulations': 200,
                    'popular_books_updated': 50
                },
                'recommendations_cache': {
                    'patrons_processed': 30,
                    'recommendations_generated': 150,
                    'cache_size_kb': 300
                }
            }
            
            result = await regenerate_catalog_handler({}, ctx)
        
        assert not result.get('isError')
        content = result['content'][0]['text']
        
        # Verify warnings are included
        assert '⚠ 5 orphaned books found' in content
        assert '⚠ 3 invalid circulations found' in content
    
    async def test_handler_error_handling(self):
        """Test handler error handling."""
        ctx = AsyncMock(spec=Context)
        
        with patch('tools.catalog_maintenance.regenerate_catalog') as mock_regenerate:
            mock_regenerate.side_effect = Exception("Database connection failed")
            
            result = await regenerate_catalog_handler({}, ctx)
        
        assert result['isError']
        assert 'Catalog regeneration failed: Database connection failed' in result['content'][0]['text']