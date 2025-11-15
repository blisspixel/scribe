"""
Unit tests for run context and observability.

Tests run ID generation, context management, metadata tracking,
and run history functionality.
"""

import time
import pytest
import threading
from datetime import datetime
from scribe.utils.run_context import (
    RunContext,
    get_current_run_id,
    add_run_metadata,
    nested_operation,
    RunHistory,
    get_run_history,
    _generate_run_id
)


class TestRunIDGeneration:
    """Test run ID generation."""
    
    def test_generate_run_id_format(self):
        """Test run ID has correct format."""
        run_id = _generate_run_id()
        
        # Format: YYYYMMDD_HHMMSS_<8-char-uuid>
        parts = run_id.split("_")
        assert len(parts) == 3
        assert len(parts[0]) == 8  # YYYYMMDD
        assert len(parts[1]) == 6  # HHMMSS
        assert len(parts[2]) == 8  # short UUID
    
    def test_generate_run_id_unique(self):
        """Test that run IDs are unique."""
        ids = [_generate_run_id() for _ in range(100)]
        
        # All IDs should be unique
        assert len(set(ids)) == 100
    
    def test_generate_run_id_sortable(self):
        """Test that run IDs are sortable by time."""
        id1 = _generate_run_id()
        time.sleep(1.1)  # Sleep long enough to ensure different timestamps
        id2 = _generate_run_id()
        
        # Later ID should sort after earlier ID
        assert id2 > id1


class TestRunContext:
    """Test RunContext class."""
    
    def test_create_context(self):
        """Test creating a run context."""
        ctx = RunContext.create("test_operation")
        
        assert ctx.run_id is not None
        assert ctx.operation == "test_operation"
        assert ctx.start_time is not None
        assert ctx.end_time is None
        assert ctx.success is None
        assert ctx.error_message is None
    
    def test_context_captures_system_info(self):
        """Test that context captures system information."""
        ctx = RunContext.create("test")
        
        assert "python_version" in ctx.metadata
        assert "platform" in ctx.metadata
        assert "pid" in ctx.metadata
    
    def test_add_metadata(self):
        """Test adding metadata to context."""
        ctx = RunContext.create("test")
        
        ctx.add_metadata("file", "test.mp4")
        ctx.add_metadata("model", "large-v3-turbo")
        
        assert ctx.metadata["file"] == "test.mp4"
        assert ctx.metadata["model"] == "large-v3-turbo"
    
    def test_mark_success(self):
        """Test marking run as successful."""
        ctx = RunContext.create("test")
        time.sleep(0.01)
        
        ctx.mark_success()
        
        assert ctx.success is True
        assert ctx.end_time is not None
        assert ctx.error_message is None
        assert ctx.get_duration() > 0
    
    def test_mark_failure(self):
        """Test marking run as failed."""
        ctx = RunContext.create("test")
        time.sleep(0.01)
        
        ctx.mark_failure("Test error")
        
        assert ctx.success is False
        assert ctx.end_time is not None
        assert ctx.error_message == "Test error"
        assert ctx.get_duration() > 0
    
    def test_get_duration_before_end(self):
        """Test getting duration before run ends."""
        ctx = RunContext.create("test")
        
        duration = ctx.get_duration()
        
        assert duration is None
    
    def test_to_dict(self):
        """Test converting context to dictionary."""
        ctx = RunContext.create("test")
        ctx.add_metadata("key", "value")
        ctx.mark_success()
        
        data = ctx.to_dict()
        
        assert data["run_id"] == ctx.run_id
        assert data["operation"] == "test"
        assert "start_time" in data
        assert "end_time" in data
        assert "duration_seconds" in data
        assert data["success"] is True
        assert data["metadata"]["key"] == "value"


class TestContextManager:
    """Test RunContext as context manager."""
    
    def test_context_manager_success(self):
        """Test context manager with successful operation."""
        with RunContext.create("test") as ctx:
            ctx.add_metadata("test", "value")
        
        assert ctx.success is True
        assert ctx.end_time is not None
    
    def test_context_manager_exception(self):
        """Test context manager with exception."""
        with pytest.raises(ValueError):
            with RunContext.create("test") as ctx:
                raise ValueError("Test error")
        
        assert ctx.success is False
        assert "ValueError" in ctx.error_message
        assert "Test error" in ctx.error_message
    
    def test_context_manager_explicit_failure(self):
        """Test explicitly marking failure in context manager."""
        with RunContext.create("test") as ctx:
            ctx.mark_failure("Explicit failure")
        
        assert ctx.success is False
        assert ctx.error_message == "Explicit failure"
    
    def test_context_manager_sets_current(self):
        """Test that context manager sets current context."""
        assert RunContext.get_current() is None
        
        with RunContext.create("test") as ctx:
            current = RunContext.get_current()
            assert current is ctx
        
        # Should be cleared after exit
        assert RunContext.get_current() is None


class TestThreadLocalStorage:
    """Test thread-local context storage."""
    
    def test_context_isolated_per_thread(self):
        """Test that contexts are isolated per thread."""
        results = {}
        
        def worker(thread_id):
            with RunContext.create(f"thread_{thread_id}") as ctx:
                ctx.add_metadata("thread_id", thread_id)
                time.sleep(0.01)
                results[thread_id] = ctx.run_id
        
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Each thread should have unique run ID
        assert len(set(results.values())) == 5
    
    def test_nested_contexts(self):
        """Test nested context managers."""
        with RunContext.create("outer") as outer_ctx:
            outer_id = get_current_run_id()
            
            with RunContext.create("inner") as inner_ctx:
                inner_id = get_current_run_id()
                
                # Inner context should be current
                assert inner_id == inner_ctx.run_id
                assert inner_id != outer_id
            
            # Outer context should be restored
            assert get_current_run_id() == outer_id


class TestConvenienceFunctions:
    """Test convenience functions."""
    
    def test_get_current_run_id(self):
        """Test getting current run ID."""
        assert get_current_run_id() is None
        
        with RunContext.create("test") as ctx:
            run_id = get_current_run_id()
            assert run_id == ctx.run_id
        
        assert get_current_run_id() is None
    
    def test_add_run_metadata(self):
        """Test adding metadata via convenience function."""
        with RunContext.create("test") as ctx:
            add_run_metadata("key1", "value1")
            add_run_metadata("key2", 42)
            
            assert ctx.metadata["key1"] == "value1"
            assert ctx.metadata["key2"] == 42
    
    def test_add_run_metadata_no_context(self):
        """Test adding metadata when no context is active."""
        # Should not raise error
        add_run_metadata("key", "value")


class TestNestedOperation:
    """Test nested operation context manager."""
    
    def test_nested_operation(self):
        """Test creating nested operation."""
        with RunContext.create("parent") as parent_ctx:
            parent_id = parent_ctx.run_id
            
            with nested_operation("child") as child_ctx:
                assert child_ctx.operation == "child"
                assert child_ctx.parent_run_id == parent_id
                assert child_ctx.run_id != parent_id
    
    def test_nested_operation_without_parent(self):
        """Test nested operation without parent context."""
        with nested_operation("operation") as ctx:
            assert ctx.operation == "operation"
            assert ctx.parent_run_id is None


class TestRunHistory:
    """Test RunHistory class."""
    
    def test_add_run(self):
        """Test adding run to history."""
        history = RunHistory(max_size=10)
        
        ctx = RunContext.create("test")
        ctx.mark_success()
        
        history.add(ctx)
        
        assert len(history.runs) == 1
        assert history.runs[0] is ctx
    
    def test_max_size_limit(self):
        """Test that history respects max size."""
        history = RunHistory(max_size=5)
        
        for i in range(10):
            ctx = RunContext.create(f"test_{i}")
            ctx.mark_success()
            history.add(ctx)
        
        # Should only keep last 5
        assert len(history.runs) == 5
        assert history.runs[-1].operation == "test_9"
    
    def test_get_recent(self):
        """Test getting recent runs."""
        history = RunHistory(max_size=10)
        
        for i in range(5):
            ctx = RunContext.create(f"test_{i}")
            ctx.mark_success()
            history.add(ctx)
        
        recent = history.get_recent(count=3)
        
        assert len(recent) == 3
        # Should be newest first
        assert recent[0].operation == "test_4"
        assert recent[1].operation == "test_3"
        assert recent[2].operation == "test_2"
    
    def test_get_by_id(self):
        """Test getting run by ID."""
        history = RunHistory(max_size=10)
        
        ctx = RunContext.create("test")
        ctx.mark_success()
        history.add(ctx)
        
        found = history.get_by_id(ctx.run_id)
        
        assert found is ctx
    
    def test_get_by_id_not_found(self):
        """Test getting non-existent run by ID."""
        history = RunHistory(max_size=10)
        
        found = history.get_by_id("nonexistent")
        
        assert found is None
    
    def test_get_failed_runs(self):
        """Test getting failed runs."""
        history = RunHistory(max_size=10)
        
        # Add mix of successful and failed runs
        for i in range(5):
            ctx = RunContext.create(f"test_{i}")
            if i % 2 == 0:
                ctx.mark_success()
            else:
                ctx.mark_failure("Test error")
            history.add(ctx)
        
        failed = history.get_failed_runs()
        
        assert len(failed) == 2
        assert all(r.success is False for r in failed)
    
    def test_clear(self):
        """Test clearing history."""
        history = RunHistory(max_size=10)
        
        for i in range(5):
            ctx = RunContext.create(f"test_{i}")
            ctx.mark_success()
            history.add(ctx)
        
        history.clear()
        
        assert len(history.runs) == 0
    
    def test_thread_safety(self):
        """Test that history is thread-safe."""
        history = RunHistory(max_size=100)
        
        def worker():
            for i in range(10):
                ctx = RunContext.create("test")
                ctx.mark_success()
                history.add(ctx)
        
        threads = [threading.Thread(target=worker) for _ in range(5)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Should have 50 runs total
        assert len(history.runs) == 50


class TestGlobalRunHistory:
    """Test global run history instance."""
    
    def test_get_run_history(self):
        """Test getting global run history."""
        history = get_run_history()
        
        assert isinstance(history, RunHistory)
        assert history.max_size == 100
    
    def test_global_history_persistence(self):
        """Test that global history persists across calls."""
        history1 = get_run_history()
        history2 = get_run_history()
        
        # Should be same instance
        assert history1 is history2


class TestIntegration:
    """Integration tests for run context."""
    
    def test_complete_workflow(self):
        """Test complete workflow with context and history."""
        history = get_run_history()
        initial_count = len(history.runs)
        
        with RunContext.create("transcribe") as ctx:
            add_run_metadata("file", "test.mp4")
            add_run_metadata("method", "local")
            
            with nested_operation("convert") as convert_ctx:
                add_run_metadata("format", "wav")
                convert_ctx.mark_success()
            
            with nested_operation("process") as process_ctx:
                add_run_metadata("model", "large-v3-turbo")
                process_ctx.mark_success()
            
            ctx.mark_success()
        
        # Context should be complete
        assert ctx.success is True
        assert ctx.metadata["file"] == "test.mp4"
        assert ctx.metadata["method"] == "local"
        
        # History should have the runs
        assert len(history.runs) >= initial_count + 3

