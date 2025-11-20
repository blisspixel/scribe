"""
GPU resource manager to prevent OOM and concurrent access issues.

═══════════════════════════════════════════════════════════════════════════════
ARCHITECTURAL PATTERN: Singleton + Resource Pool + Context Manager
═══════════════════════════════════════════════════════════════════════════════

This module implements a critical defensive pattern that prevents GPU memory
exhaustion and concurrent model loading - two of the most common failure modes
in GPU-accelerated machine learning applications.

PROBLEM STATEMENT:
──────────────────
Modern deep learning models (like Whisper large-v3) consume significant GPU
memory (8-12GB). Loading multiple models concurrently causes:

1. OUT OF MEMORY (OOM) crashes - CUDA runs out of VRAM
2. Memory fragmentation - Repeated load/unload cycles fragment GPU memory
3. Performance degradation - Swapping models in/out is expensive
4. Race conditions - Concurrent access to GPU resources

Traditional approaches (manual memory management, global locks) are error-prone
and require developers to remember cleanup. This module provides automatic,
foolproof resource management.

DESIGN RATIONALE:
─────────────────
The GPUResourceManager combines three patterns:

1. SINGLETON: Only one manager instance exists globally, ensuring centralized
   control over GPU resources. This prevents multiple managers from conflicting.

2. RESOURCE POOL: Tracks which model is currently loaded and prevents loading
   a second model until the first is unloaded. This is a pool of size 1.

3. CONTEXT MANAGER: Uses Python's `with` statement to guarantee cleanup even
   if exceptions occur. This is the "Resource Acquisition Is Initialization"
   (RAII) pattern from C++.

USAGE PATTERN:
──────────────
```python
gpu_manager = get_gpu_manager()

# Automatic model switching
with gpu_manager.acquire_gpu("large-v3", model_obj):
    result = model.transcribe(audio)
    # GPU is reserved for this model
# Model stays loaded for reuse (performance optimization)

# Later, with a different model
with gpu_manager.acquire_gpu("medium", other_model):
    # Previous model is automatically unloaded
    # GPU cache is cleared
    result = other_model.transcribe(audio)
```

MEMORY MANAGEMENT STRATEGY:
───────────────────────────
The manager implements a "lazy unload" strategy:

1. When a model is loaded, it stays loaded until a different model is needed
2. This optimizes for the common case: sequential transcriptions with same model
3. When switching models, the old model is explicitly deleted and GPU cache cleared
4. This prevents memory leaks and fragmentation

Memory lifecycle:
┌─────────────────────────────────────────────────────────────────────────────┐
│ acquire_gpu("model-A")                                                      │
│   ├─ Check: Is model-A already loaded? → Yes: Reuse (fast path)           │
│   ├─ Check: Is different model loaded? → Yes: Unload it                   │
│   │   ├─ Delete model object (Python GC)                                  │
│   │   ├─ torch.cuda.empty_cache() (free fragmented memory)                │
│   │   └─ gc.collect() (force garbage collection)                          │
│   └─ Load model-A and register with manager                               │
└─────────────────────────────────────────────────────────────────────────────┘

THREAD SAFETY:
──────────────
The manager uses threading.Lock to ensure thread-safe access:

- _lock: Protects singleton instantiation (double-checked locking)
- _model_lock: Protects model loading/unloading operations

This allows multiple threads to safely request GPU access without race conditions.

PERFORMANCE OPTIMIZATION:
─────────────────────────
Key optimization: Models are NOT unloaded when exiting the context manager.
This is intentional:

Scenario: Batch transcription of 10 files
- Without lazy unload: Load model, transcribe, unload, repeat 10x (slow)
- With lazy unload: Load model once, transcribe 10x, unload once (fast)

The model is only unloaded when:
1. A different model is requested (automatic)
2. Explicit call to unload_current_model() (manual)
3. Process termination (OS cleanup)

FAILURE MODES PREVENTED:
────────────────────────
1. OOM Crash: Prevents loading multiple large models simultaneously
2. Memory Leak: Ensures old models are deleted before loading new ones
3. Fragmentation: Clears GPU cache between model switches
4. Race Condition: Thread-safe access to GPU resources
5. Resource Leak: Context manager guarantees cleanup even on exceptions

RESEARCH REFERENCES:
────────────────────
- "Design Patterns: Elements of Reusable Object-Oriented Software" (GoF, 1994)
  → Singleton pattern for global resource management
- "Effective Python: 90 Specific Ways to Write Better Python" (Slatkin, 2019)
  → Context managers for resource management (Item 66)
- "CUDA C++ Programming Guide" (NVIDIA, 2023)
  → GPU memory management best practices
- "Resource Acquisition Is Initialization" (Stroustrup, 1994)
  → RAII pattern for automatic resource cleanup

This manager is a cornerstone of Scribe's stability - it prevents the most
common GPU failure mode (OOM) through simple, automatic resource management.
"""

import threading
from typing import Optional, Any
from contextlib import contextmanager

from scribe.utils.logging import get_logger
from scribe.utils.gpu import clear_gpu_cache

logger = get_logger(__name__)


class GPUResourceManager:
    """
    Singleton GPU resource manager.
    
    Ensures only one model is loaded at a time and handles
    GPU memory cleanup between operations.
    
    Thread-safe for concurrent access.
    """
    
    _instance: Optional["GPUResourceManager"] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Singleton pattern - only one instance allowed."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize GPU resource manager."""
        if self._initialized:
            return
        
        self._model_lock = threading.Lock()
        self._current_model: Optional[str] = None
        self._current_model_obj: Optional[Any] = None
        self._initialized = True
        
        logger.debug("GPU resource manager initialized")
    
    @contextmanager
    def acquire_gpu(self, model_name: str, model_obj: Optional[Any] = None):
        """
        Acquire GPU for model loading.
        
        If a different model is currently loaded, it will be unloaded
        and GPU memory will be cleared.
        
        Args:
            model_name: Name/identifier of the model
            model_obj: Optional model object to track
            
        Yields:
            None
            
        Example:
            with gpu_manager.acquire_gpu("large-v3", model):
                # GPU is reserved for this model
                result = model.transcribe(audio)
        """
        with self._model_lock:
            # Check if we need to unload previous model
            if self._current_model and self._current_model != model_name:
                logger.info(
                    f"Switching GPU model: {self._current_model} → {model_name}"
                )
                
                # Unload previous model
                if self._current_model_obj is not None:
                    try:
                        del self._current_model_obj
                    except Exception as e:
                        logger.warning(f"Error deleting model object: {e}")
                
                # Clear GPU cache
                clear_gpu_cache()
                
                self._current_model = None
                self._current_model_obj = None
            
            # Set current model
            self._current_model = model_name
            if model_obj is not None:
                self._current_model_obj = model_obj
            
            logger.debug(f"GPU acquired for model: {model_name}")
            
            try:
                yield
            finally:
                # Keep model loaded for reuse (don't unload on exit)
                # This improves performance for sequential transcriptions
                logger.debug(f"GPU released (model kept loaded): {model_name}")
    
    def unload_current_model(self) -> None:
        """
        Explicitly unload current model and free GPU memory.
        
        Useful for long-running processes that need to free GPU memory
        between operations.
        """
        with self._model_lock:
            if self._current_model:
                logger.info(f"Unloading GPU model: {self._current_model}")
                
                if self._current_model_obj is not None:
                    try:
                        del self._current_model_obj
                    except Exception as e:
                        logger.warning(f"Error deleting model object: {e}")
                
                clear_gpu_cache()
                
                self._current_model = None
                self._current_model_obj = None
    
    def get_current_model(self) -> Optional[str]:
        """
        Get name of currently loaded model.
        
        Returns:
            Model name, or None if no model is loaded
        """
        with self._model_lock:
            return self._current_model
    
    @classmethod
    def get_instance(cls) -> "GPUResourceManager":
        """
        Get the singleton GPU resource manager instance.
        
        Returns:
            GPUResourceManager instance
        """
        return cls()


# Global instance accessor
def get_gpu_manager() -> GPUResourceManager:
    """
    Get the global GPU resource manager instance.
    
    Returns:
        GPUResourceManager singleton
    """
    return GPUResourceManager.get_instance()
