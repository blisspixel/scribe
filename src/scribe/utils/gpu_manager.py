"""
GPU resource manager to prevent OOM and concurrent access issues.

This module provides a singleton GPU resource manager that ensures
only one model is loaded at a time and handles GPU memory cleanup.
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
