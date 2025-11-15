"""
Unit tests for unified progress tracking.
"""

import pytest
from unittest.mock import Mock, patch
import time

from scribe.utils.unified_progress import UnifiedProgress


class TestUnifiedProgress:
    """Test unified progress tracker."""
    
    def test_initialization(self):
        """Test progress initialization."""
        progress = UnifiedProgress(total_duration=3600)
        
        assert progress.total_duration == 3600
        assert progress.current_phase is None
        assert progress.progress is None
    
    def test_phase_definitions(self):
        """Test phase definitions are correct."""
        # Without API features (transcribe only)
        progress = UnifiedProgress(include_api_features=False)
        
        assert "preparing" in progress.phases
        assert "transcribing" in progress.phases
        assert "finishing" in progress.phases
        
        # Check phase ranges for transcribe-only workflow
        assert progress.phases["preparing"][0] == 0
        assert progress.phases["preparing"][1] == 42  # 41.8% preparing
        assert progress.phases["transcribing"][0] == 42
        assert progress.phases["transcribing"][1] == 99  # 58.3% transcribing
        assert progress.phases["finishing"][0] == 99
        assert progress.phases["finishing"][1] == 100  # 0.04% finishing
        
        # With API features (full workflow)
        progress_with_api = UnifiedProgress(include_api_features=True)
        assert progress_with_api.phases["preparing"][1] == 19  # 18.9% preparing
        assert progress_with_api.phases["transcribing"][1] == 45  # 26.4% transcribing
        assert progress_with_api.phases["finishing"][1] == 100  # 54.7% finishing
    
    @patch('scribe.utils.unified_progress.Progress')
    def test_start(self, mock_progress_class):
        """Test starting progress display."""
        mock_progress = Mock()
        mock_progress_class.return_value = mock_progress
        
        progress = UnifiedProgress()
        progress.start()
        
        assert mock_progress.start.called
        assert mock_progress.add_task.called
    
    @patch('scribe.utils.unified_progress.Progress')
    def test_update_phase(self, mock_progress_class):
        """Test updating progress within a phase."""
        mock_progress = Mock()
        mock_task = Mock()
        mock_progress.add_task.return_value = mock_task
        mock_progress_class.return_value = mock_progress
        
        progress = UnifiedProgress(include_api_features=False)
        progress.start()
        
        # Update to 50% through preparing phase (0-42%)
        progress.update_phase("preparing", 0.5)
        
        # Should be at 21% overall (0 + 0.5 * 42)
        assert mock_progress.update.called
        call_args = mock_progress.update.call_args
        assert call_args[1]["completed"] == 21.0
    
    @patch('scribe.utils.unified_progress.Progress')
    def test_complete(self, mock_progress_class):
        """Test completing progress."""
        mock_progress = Mock()
        mock_progress_class.return_value = mock_progress
        
        progress = UnifiedProgress()
        progress.start()
        progress.complete()
        
        # Should update to 100% and stop
        assert mock_progress.update.called
        assert mock_progress.stop.called
    
    def test_phase_progress_calculation(self):
        """Test progress calculation across phases."""
        progress = UnifiedProgress(include_api_features=False)
        
        # Test preparing phase (0-42%)
        start, end, _ = progress.phases["preparing"]
        assert start == 0
        assert end == 42
        
        # 0% through preparing = 0% overall
        overall = start + (0.0 * (end - start))
        assert overall == 0
        
        # 100% through preparing = 42% overall
        overall = start + (1.0 * (end - start))
        assert overall == 42
        
        # Test transcribing phase (42-99%)
        start, end, _ = progress.phases["transcribing"]
        assert start == 42
        assert end == 99
        
        # 50% through transcribing = 70.5% overall (42 + 0.5 * 57)
        overall = start + (0.5 * (end - start))
        assert overall == 70.5
