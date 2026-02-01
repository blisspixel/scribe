"""
OpenAI API transcription module with chunking and bug fixes.

This module provides cloud-based transcription using OpenAI's API with:
- Audio standardization (phase-safe mono, 16kHz)
- Silence-based chunking with duration cap
- Exponential backoff retry logic
- CRITICAL FIX: Proper text concatenation and file flushing
"""

import time
import random
from pathlib import Path
from typing import Optional, List, Tuple

import numpy as np
from pydub import AudioSegment
from pydub.silence import split_on_silence
from openai import OpenAI, APIConnectionError, RateLimitError, APIStatusError, AuthenticationError
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

from scribe.exceptions import APIError, TranscriptionError
from scribe.utils.files import verify_file_content, extract_date_from_filename, format_date, format_duration_minutes
from scribe.utils.logging import console, get_logger

logger = get_logger(__name__)


class OpenAITranscriber:
    """
    OpenAI API-based transcription with chunking for large files.
    
    This class handles:
    - Audio standardization to optimal format
    - Chunking large files to stay under API limits
    - Retry logic with exponential backoff
    - Proper text concatenation (fixes blank file bug)
    """
    
    def __init__(
        self, 
        api_key: str, 
        model: str = "gpt-4o-transcribe",
        use_server_chunking: bool = True
    ):
        """
        Initialize OpenAI transcriber.
        
        Args:
            api_key: OpenAI API key
            model: Model to use (default: gpt-4o-transcribe)
            use_server_chunking: Use OpenAI's server-side chunking (recommended)
        """
        self.api_key = api_key
        self.model = model
        self.use_server_chunking = use_server_chunking
        self.client = OpenAI(api_key=api_key)
        
        logger.debug(f"Initialized OpenAI transcriber with model: {model}")
    
    def transcribe_with_server_chunking(
        self,
        audio_path: Path,
        output_path: Path,
        prompt: Optional[str] = None
    ) -> Path:
        """
        Transcribe using OpenAI's server-side chunking (2025 best practice).
        
        This method uses chunking_strategy="auto" to let OpenAI handle
        long audio files server-side using Voice Activity Detection.
        
        Args:
            audio_path: Path to audio file
            output_path: Path for output transcript
            prompt: Optional glossary/prompt
            
        Returns:
            Path to transcript file
        """
        logger.info(f"Using server-side chunking for: {audio_path.name}")
        
        try:
            with open(audio_path, "rb") as audio_file:
                logger.info(f"Uploading to OpenAI ({self.model})...")
                
                # Build params according to OpenAI docs
                params = {
                    "model": self.model,
                    "file": audio_file,
                }
                
                # Configure response format based on model
                if "diarize" in self.model:
                    # New diarization models only support 'json' format, not 'verbose_json'
                    params["response_format"] = "json"
                    params["timestamp_granularities"] = ["word"]
                    # chunking_strategy is required for diarize models with long audio
                    params["chunking_strategy"] = "auto"
                else:
                    params["response_format"] = "text"
                    # Add prompt if provided (not supported for diarize models)
                    if prompt:
                        params["prompt"] = prompt
                
                try:
                    transcript_response = self.client.audio.transcriptions.create(**params)
                except Exception as api_error:
                    # If chunking_strategy fails, retry without it
                    if "chunking_strategy" in str(api_error) and "chunking_strategy" in params:
                        logger.warning("chunking_strategy not supported, retrying without it...")
                        del params["chunking_strategy"]
                        transcript_response = self.client.audio.transcriptions.create(**params)
                    else:
                        raise
                
            # Extract text and format with speaker labels if available
            logger.info("Processing transcription response...")
            
            # Format the output
            formatted_text = self._format_transcript_response(
                transcript_response,
                audio_path
            )
            
            # Write output
            logger.info(f"Writing transcript to: {output_path}")
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(formatted_text)
            
            # Verify output
            verify_file_content(output_path, min_size=10)
            logger.info(f"Transcription verified: {output_path.name}")
            
            return output_path
            
        except AuthenticationError as e:
            raise APIError(
                "OpenAI API authentication failed",
                context={"error": str(e), "key_prefix": self.api_key[:10]}
            )
        except Exception as e:
            error_msg = str(e)
            # Check for duration limit error - retry with client-side chunking
            if "longer than" in error_msg and "seconds" in error_msg:
                logger.warning("Hit OpenAI duration limit, retrying with client-side chunking...")
                self.use_server_chunking = False
                return self.transcribe(audio_path, output_path, prompt)
            
            raise TranscriptionError(
                f"Server-side chunking transcription failed: {e}",
                context={"audio_path": str(audio_path), "model": self.model}
            )
    
    def _format_transcript_response(
        self,
        response,
        audio_path: Path
    ) -> str:
        """
        Format transcription response with header and speaker labels.
        
        Args:
            response: OpenAI API response (string if response_format="text", object if "json")
            audio_path: Original audio file path
            
        Returns:
            Formatted transcript text
        """
        # Extract metadata
        meeting_name = audio_path.stem
        for suffix in ['_16k_mono', '_standardized', '_converted']:
            meeting_name = meeting_name.replace(suffix, '')
        
        date_str = extract_date_from_filename(audio_path.name)
        formatted_date = format_date(date_str) if date_str else "Unknown"
        
        # Get duration if available
        duration_str = "Unknown"
        if hasattr(response, 'duration'):
            duration_str = format_duration_minutes(int(response.duration))
        
        # Build header
        lines = [
            f"Meeting: {meeting_name}",
            f"Date: {formatted_date}",
            f"Duration: {duration_str}",
            "",
            "─" * 80,
            ""
        ]
        
        # Handle different response formats defensively
        if isinstance(response, str):
            # response_format="text" returns a plain string
            lines.append(response.strip())
        elif hasattr(response, 'segments') and response.segments:
            # response_format="verbose_json" with segments (diarization)
            try:
                for segment in response.segments:
                    # Safely extract segment data
                    if isinstance(segment, dict):
                        start = segment.get('start', 0)
                        text = segment.get('text', '').strip()
                        speaker = segment.get('speaker')
                    else:
                        start = getattr(segment, 'start', 0)
                        text = getattr(segment, 'text', '').strip()
                        speaker = getattr(segment, 'speaker', None)
                    
                    # Skip empty segments
                    if not text:
                        continue
                    
                    timestamp = self._format_timestamp(start)
                    
                    # Format with speaker label if available
                    if speaker:
                        lines.append(f"[{timestamp}] {speaker}: {text}")
                    else:
                        lines.append(f"[{timestamp}] {text}")
                    lines.append("")
            except Exception as e:
                logger.warning(f"Error processing segments: {e}, falling back to text extraction")
                # Fallback to text attribute if segment processing fails
                if hasattr(response, 'text'):
                    lines.append(response.text.strip())
        elif hasattr(response, 'text'):
            # response_format="json" or "verbose_json" with simple text
            lines.append(response.text.strip())
        else:
            # Fallback - convert to string
            logger.warning(f"Unexpected response format: {type(response)}")
            lines.append(str(response).strip())
        
        return "\n".join(lines)
    
    def _format_timestamp(self, seconds: float) -> str:
        """Format seconds as HH:MM:SS."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    
    def standardize_audio(
        self,
        input_path: Path,
        target_bitrate_kbps: int = 48
    ) -> Path:
        """
        Convert audio to stable format for ASR.
        
        Creates phase-safe mono 16kHz MP3 at target bitrate.
        
        Args:
            input_path: Original audio file
            target_bitrate_kbps: Target MP3 bitrate
            
        Returns:
            Path to standardized audio file
        """
        logger.info(f"Standardizing audio (phase-safe mono, 16kHz, {target_bitrate_kbps}kbps MP3)...")
        
        audio = AudioSegment.from_file(str(input_path))
        logger.debug(
            f"Source: {len(audio)/1000:.1f}s, "
            f"{audio.channels}ch, "
            f"{audio.frame_rate}Hz"
        )
        
        use_channel = None
        
        # Analyze stereo for phase issues
        if audio.channels >= 2:
            probe = audio[:min(30_000, len(audio))]
            samples = np.array(probe.get_array_of_samples()).reshape((-1, audio.channels)).astype(np.int16)
            
            L = samples[:, 0].astype(np.float32)
            R = samples[:, 1].astype(np.float32)
            corr = float(np.corrcoef(L + 1e-6, R + 1e-6)[0, 1])
            rmsL = 20.0 * np.log10(max(1e-9, np.sqrt(np.mean(L * L)) / 32768.0))
            rmsR = 20.0 * np.log10(max(1e-9, np.sqrt(np.mean(R * R)) / 32768.0))
            
            logger.debug(f"Stereo analysis: corr={corr:+.3f}, rmsL={rmsL:.1f}dBFS, rmsR={rmsR:.1f}dBFS")
            
            # Pick single channel if phase issues or imbalance
            if corr < -0.5 or abs(rmsL - rmsR) > 6.0:
                use_channel = "L" if rmsL >= rmsR else "R"
                logger.info(f"Phase/imbalance detected. Using {use_channel}-only channel.")
        
        # Convert to mono
        if use_channel and audio.channels >= 2:
            L, R = audio.split_to_mono()[:2]
            chosen = L if use_channel == "L" else R
            stable = chosen.set_frame_rate(16000)
        else:
            stable = audio.set_channels(1).set_frame_rate(16000)
        
        # Normalize audio level if too quiet
        current_dbfs = stable.dBFS
        logger.debug(f"Current audio level: {current_dbfs:.1f}dBFS")
        
        # Target -20dBFS for good transcription (not too loud, not too quiet)
        target_dbfs = -20.0
        if current_dbfs < -35:  # If very quiet
            gain_needed = target_dbfs - current_dbfs
            logger.info(f"Audio is quiet ({current_dbfs:.1f}dBFS), normalizing with +{gain_needed:.1f}dB gain")
            stable = stable.apply_gain(gain_needed)
        elif current_dbfs < -25:  # If somewhat quiet
            gain_needed = target_dbfs - current_dbfs
            logger.info(f"Boosting audio level by +{gain_needed:.1f}dB for better transcription")
            stable = stable.apply_gain(gain_needed)
        
        # Export as MP3
        standardized_path = input_path.with_name(f"{input_path.stem}_standardized.mp3")
        stable.export(
            str(standardized_path),
            format="mp3",
            bitrate=f"{target_bitrate_kbps}k"
        )
        
        # Verify final level
        std = AudioSegment.from_file(str(standardized_path))
        logger.debug(f"Final audio level: {std.dBFS:.1f}dBFS")
        if std.dBFS < -30:
            logger.warning(f"Audio level is still low ({std.dBFS:.1f}dBFS) - transcription quality may be affected")
        
        logger.info(f"Standardized audio: {standardized_path.name}")
        return standardized_path
    
    def split_audio_on_silence(
        self,
        file_path: Path,
        max_chunk_minutes: int = 9,
        min_silence_len_ms: int = 500,
        silence_thresh_delta_db: int = -30,
        keep_silence_ms: int = 300,
        export_bitrate_kbps: int = 48
    ) -> List[Path]:
        """
        Split audio on silence with duration cap.
        
        Args:
            file_path: Path to audio file
            max_chunk_minutes: Maximum chunk duration
            min_silence_len_ms: Minimum silence length to split on
            silence_thresh_delta_db: Silence threshold relative to average
            keep_silence_ms: Silence to keep at boundaries
            export_bitrate_kbps: Export bitrate for chunks
            
        Returns:
            List of chunk file paths
        """
        logger.info("Splitting audio into chunks...")
        
        audio = AudioSegment.from_file(str(file_path))
        silence_thresh = audio.dBFS + silence_thresh_delta_db
        
        # Split on silence
        parts = split_on_silence(
            audio,
            min_silence_len=min_silence_len_ms,
            silence_thresh=silence_thresh,
            keep_silence=keep_silence_ms
        )
        
        # Cap chunk duration
        cap_ms = max_chunk_minutes * 60 * 1000
        chunks: List[AudioSegment] = []
        current = AudioSegment.silent(duration=0)
        
        for part in parts:
            if len(current) + len(part) > cap_ms:
                if len(current) > 0:
                    chunks.append(current)
                current = AudioSegment.silent(duration=0)
            current += part
        
        if len(current) > 0:
            chunks.append(current)
        
        # Export chunks
        out_paths: List[Path] = []
        stem = file_path.stem
        
        for i, chunk in enumerate(chunks, 1):
            out_name = file_path.parent / f"{stem}_chunk_{i}.mp3"
            chunk.export(
                str(out_name),
                format="mp3",
                bitrate=f"{export_bitrate_kbps}k"
            )
            out_paths.append(out_name)
        
        logger.info(f"Created {len(out_paths)} chunks for transcription")
        return out_paths
    
    def transcribe_chunk(
        self,
        chunk_path: Path,
        prompt: Optional[str] = None,
        retries: int = 5
    ) -> Tuple[bool, Optional[str]]:
        """
        Transcribe a single chunk with retry logic.
        
        Args:
            chunk_path: Path to audio chunk
            prompt: Optional glossary/prompt
            retries: Number of retry attempts
            
        Returns:
            Tuple of (success, text)
        """
        for attempt in range(retries):
            try:
                with open(chunk_path, "rb") as f:
                    kwargs = {
                        "model": self.model,
                        "file": f,
                        "response_format": "text"
                    }
                    
                    if prompt:
                        kwargs["prompt"] = prompt
                    
                    response = self.client.audio.transcriptions.create(**kwargs)
                    
                    # Extract text
                    if hasattr(response, "text"):
                        text = response.text
                    else:
                        text = str(response)
                    
                    return True, text
                    
            except (APIConnectionError, RateLimitError, APIStatusError, AuthenticationError) as e:
                logger.warning(f"API error ({chunk_path.name}, attempt {attempt + 1}): {e}")
                
                if attempt < retries - 1:
                    sleep_time = (2 ** attempt) + random.uniform(0, 1)
                    logger.info(f"Retrying in {sleep_time:.2f}s...")
                    time.sleep(sleep_time)
                else:
                    return False, None
                    
            except Exception as e:
                logger.error(f"Unexpected error on {chunk_path.name}: {e}")
                return False, None
        
        return False, None
    
    def transcribe(
        self,
        audio_path: Path,
        output_path: Optional[Path] = None,
        prompt: Optional[str] = None,
        cleanup_temp: bool = True,
        initial_prompt: Optional[str] = None
    ) -> Path:
        """
        Transcribe audio file with chunking.
        
        CRITICAL: This method includes the fix for blank output files.
        
        Args:
            audio_path: Path to audio file
            output_path: Optional output path
            prompt: Optional glossary/prompt (deprecated, use initial_prompt)
            cleanup_temp: Whether to clean up temporary files
            initial_prompt: Optional prompt to guide transcription (for custom vocabulary)
            
        Returns:
            Path to transcript file
            
        Raises:
            TranscriptionError: If transcription fails
        """
        logger.info(f"Starting OpenAI transcription: {audio_path.name}")
        
        # Generate output path - use original filename without intermediate suffixes
        if output_path is None:
            # Remove intermediate suffixes like _16k_mono, _standardized, etc.
            clean_stem = audio_path.stem
            for suffix in ['_16k_mono', '_standardized', '_converted']:
                clean_stem = clean_stem.replace(suffix, '')
            output_path = audio_path.parent / f"{clean_stem}_transcription.txt"
        
        # Check duration to decide chunking strategy
        from scribe.utils.audio import get_audio_duration
        duration = get_audio_duration(audio_path)
        
        # OpenAI has an undocumented ~1400 second (23 minute) limit per file
        # Use client-side chunking for longer files
        if duration and duration > 1300:  # 21.6 minutes, leave buffer
            logger.info(f"Audio is {duration/60:.1f} minutes, using client-side chunking")
            self.use_server_chunking = False
        
        # Use initial_prompt if provided, otherwise fall back to prompt
        effective_prompt = initial_prompt or prompt
        
        # Use server-side chunking if enabled and file is short enough
        if self.use_server_chunking:
            logger.info("Using server-side chunking (single API call)")
            return self.transcribe_with_server_chunking(audio_path, output_path, effective_prompt)
        
        # Legacy client-side chunking (fallback)
        logger.info("Using client-side chunking (legacy mode)")
        temp_files: List[Path] = []
        
        try:
            # Step 1: Standardize audio
            standardized_path = self.standardize_audio(audio_path)
            temp_files.append(standardized_path)
            
            # Step 2: Split into chunks
            chunk_paths = self.split_audio_on_silence(standardized_path)
            temp_files.extend(chunk_paths)
            
            # Step 3: Transcribe chunks with progress
            logger.info(f"Transcribing {len(chunk_paths)} chunks...")
            
            transcripts: List[str] = []
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]Transcribing chunks..."),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TextColumn("({task.completed}/{task.total})"),
                TimeElapsedColumn(),
                console=console,
                transient=False
            ) as progress:
                task = progress.add_task("Transcribing", total=len(chunk_paths))
                
                for i, chunk_path in enumerate(chunk_paths, 1):
                    logger.debug(f"Transcribing chunk {i}/{len(chunk_paths)}: {chunk_path.name}")
                    
                    success, text = self.transcribe_chunk(chunk_path, prompt=prompt)
                    
                    if success and text:
                        transcripts.append(text.strip())
                        logger.debug(f"Chunk {i} transcribed: {len(text)} characters")
                    else:
                        logger.warning(f"Chunk {i} failed, skipping")
                    
                    progress.update(task, advance=1)
                    time.sleep(1.2)  # Rate limiting
            
            # Step 4: CRITICAL FIX - Combine transcripts with proper flushing
            logger.info("Combining transcripts...")
            
            if not transcripts:
                raise TranscriptionError(
                    "No transcripts generated from any chunks",
                    context={"chunks": len(chunk_paths)}
                )
            
            # Write combined transcript with explicit flushing
            with open(output_path, "w", encoding="utf-8") as f:
                # Write header
                meeting_name = audio_path.stem.replace("_standardized", "")
                date_str = extract_date_from_filename(audio_path.name)
                
                if date_str:
                    f.write(f"Meeting: {meeting_name}\n")
                    f.write(f"Date: {format_date(date_str)}\n")
                else:
                    f.write(f"Transcription: {meeting_name}\n")
                
                f.write("\n")
                f.write("─" * 80 + "\n")
                f.write("\n")
                f.flush()  # CRITICAL: Flush header
                
                # Write each transcript with spacing
                for i, text in enumerate(transcripts, 1):
                    if text:
                        f.write(text.strip())
                        f.write("\n\n")
                        f.flush()  # CRITICAL: Flush after each chunk
                        logger.debug(f"Wrote chunk {i} to file")
                
                # Final flush
                f.flush()
            
            # Step 5: CRITICAL FIX - Verify output is not empty
            try:
                verify_file_content(output_path, min_size=100)
                logger.info(f"Transcription verified: {output_path.name}")
            except Exception as e:
                raise TranscriptionError(
                    "Output file is empty or too small",
                    context={
                        "output_path": str(output_path),
                        "file_size": output_path.stat().st_size if output_path.exists() else 0,
                        "error": str(e)
                    }
                )
            
            logger.info(f"Transcription complete: {output_path}")
            return output_path
            
        finally:
            # Cleanup temporary files
            if cleanup_temp:
                logger.debug("Cleaning up temporary files...")
                for temp_file in temp_files:
                    try:
                        if temp_file.exists():
                            temp_file.unlink()
                            logger.debug(f"Deleted: {temp_file.name}")
                    except Exception as e:
                        logger.warning(f"Could not delete {temp_file.name}: {e}")


def transcribe_with_openai(
    audio_path: Path,
    api_key: str,
    model: str = "gpt-4o-transcribe",
    **kwargs
) -> Path:
    """
    Convenience function for OpenAI transcription.
    
    Args:
        audio_path: Path to audio file
        api_key: OpenAI API key
        model: Model to use
        **kwargs: Additional arguments for OpenAITranscriber.transcribe()
        
    Returns:
        Path to transcript file
    """
    transcriber = OpenAITranscriber(api_key=api_key, model=model)
    return transcriber.transcribe(audio_path, **kwargs)
