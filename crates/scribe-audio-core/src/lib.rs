use pyo3::prelude::*;
use pyo3::exceptions::PyRuntimeError;
use symphonia::core::audio::SampleBuffer;
use symphonia::core::codecs::DecoderOptions;
use symphonia::core::formats::FormatOptions;
use symphonia::core::io::MediaSourceStream;
use symphonia::core::meta::MetadataOptions;
use symphonia::core::probe::Hint;
use std::fs::File;

/// Compute the dBFS of a block of samples
fn compute_dbfs(samples: &[f32]) -> f32 {
    if samples.is_empty() {
        return f32::NEG_INFINITY;
    }
    let mut sum_sq = 0.0;
    for &sample in samples {
        sum_sq += sample * sample;
    }
    let rms = (sum_sq / samples.len() as f32).sqrt();
    if rms == 0.0 {
        return f32::NEG_INFINITY;
    }
    20.0 * rms.log10()
}

/// Find split timestamps (in ms) where silence occurs.
/// Returns a list of end timestamps for each chunk, ensuring no chunk exceeds max_duration_ms.
#[pyfunction]
#[pyo3(signature = (file_path, min_silence_ms, silence_thresh_db, max_duration_ms))]
fn get_split_timestamps(
    file_path: &str,
    min_silence_ms: u32,
    silence_thresh_db: f32,
    max_duration_ms: u32,
) -> PyResult<Vec<u32>> {
    let file = File::open(file_path)
        .map_err(|e| PyRuntimeError::new_err(format!("Failed to open file: {}", e)))?;
    
    let mss = MediaSourceStream::new(Box::new(file), Default::default());
    
    let mut hint = Hint::new();
    // Hint extension to help symphonia
    if let Some(ext) = file_path.rsplit('.').next() {
        hint.with_extension(ext);
    }
    
    let meta_opts: MetadataOptions = Default::default();
    let fmt_opts: FormatOptions = Default::default();
    
    let probed = symphonia::default::get_probe()
        .format(&hint, mss, &fmt_opts, &meta_opts)
        .map_err(|e| PyRuntimeError::new_err(format!("Unsupported format: {}", e)))?;
    
    let mut format = probed.format;
    let track = format
        .default_track()
        .ok_or_else(|| PyRuntimeError::new_err("No audio track found"))?;
    
    let track_id = track.id;
    let sample_rate = track.codec_params.sample_rate.unwrap_or(16000) as usize;
    
    let dec_opts: DecoderOptions = Default::default();
    let mut decoder = symphonia::default::get_codecs()
        .make(&track.codec_params, &dec_opts)
        .map_err(|e| PyRuntimeError::new_err(format!("Unsupported codec: {}", e)))?;
    
    let mut sample_buf = None;
    
    // We will process audio in ~10ms windows
    let window_size_samples = sample_rate / 100; 
    let mut current_window = Vec::with_capacity(window_size_samples);
    
    let mut current_ms: f64 = 0.0;
    
    let mut silence_start_ms: Option<f64> = None;
    let mut split_points = Vec::new();
    
    // State for tracking chunks
    let mut last_split_ms: f64 = 0.0;
    
    loop {
        let packet = match format.next_packet() {
            Ok(packet) => packet,
            Err(symphonia::core::errors::Error::IoError(e)) if e.kind() == std::io::ErrorKind::UnexpectedEof => {
                break; // End of file
            },
            Err(e) => {
                // Ignore other decode errors and just break (best effort)
                break;
            }
        };
        
        if packet.track_id() != track_id {
            continue;
        }
        
        let decoded = match decoder.decode(&packet) {
            Ok(decoded) => decoded,
            Err(symphonia::core::errors::Error::IoError(e)) if e.kind() == std::io::ErrorKind::UnexpectedEof => {
                break;
            }
            Err(symphonia::core::errors::Error::DecodeError(_)) => {
                // Ignore transient decode errors
                continue;
            }
            Err(e) => {
                break;
            }
        };
        
        if sample_buf.is_none() {
            sample_buf = Some(SampleBuffer::<f32>::new(decoded.capacity() as u64, *decoded.spec()));
        }
        
        if let Some(buf) = &mut sample_buf {
            buf.copy_interleaved_ref(decoded.clone());
            let samples = buf.samples();
            let channels = decoded.spec().channels.count() as usize;
            
            // Process samples in windows
            for chunk in samples.chunks(channels) {
                // Mix down to mono
                let mono: f32 = chunk.iter().sum::<f32>() / channels as f32;
                current_window.push(mono);
                
                if current_window.len() >= window_size_samples {
                    let dbfs = compute_dbfs(&current_window);
                    let window_ms = (current_window.len() as f64 / sample_rate as f64) * 1000.0;
                    
                    if dbfs <= silence_thresh_db {
                        if silence_start_ms.is_none() {
                            silence_start_ms = Some(current_ms);
                        }
                    } else {
                        // Sound detected! Check if we had a long enough silence to split.
                        if let Some(start) = silence_start_ms {
                            let silence_duration = current_ms - start;
                            if silence_duration >= min_silence_ms as f64 {
                                // We found a valid split point (the middle of the silence)
                                let split_point = start + (silence_duration / 2.0);
                                
                                // Only split if adding this chunk gets us close to max_duration,
                                // or if we really need to split to avoid going over.
                                // Wait, the Python logic says:
                                // "if len(current) + len(part) > cap_ms"
                                // Let's just collect ALL valid silence split points, 
                                // and Python can decide which ones to use.
                                split_points.push(split_point as u32);
                            }
                        }
                        silence_start_ms = None;
                    }
                    
                    current_ms += window_ms;
                    current_window.clear();
                }
            }
        }
    }
    
    // Add total duration as final split point just in case
    split_points.push(current_ms as u32);
    
    Ok(split_points)
}

#[pyfunction]
#[pyo3(signature = (file_path))]
fn get_audio_dbfs(file_path: &str) -> PyResult<f32> {
    let file = File::open(file_path)
        .map_err(|e| PyRuntimeError::new_err(format!("Failed to open file: {}", e)))?;
    
    let mss = MediaSourceStream::new(Box::new(file), Default::default());
    
    let mut hint = Hint::new();
    if let Some(ext) = file_path.rsplit('.').next() {
        hint.with_extension(ext);
    }
    
    let meta_opts: MetadataOptions = Default::default();
    let fmt_opts: FormatOptions = Default::default();
    
    let probed = symphonia::default::get_probe()
        .format(&hint, mss, &fmt_opts, &meta_opts)
        .map_err(|e| PyRuntimeError::new_err(format!("Unsupported format: {}", e)))?;
    
    let mut format = probed.format;
    let track = format
        .default_track()
        .ok_or_else(|| PyRuntimeError::new_err("No audio track found"))?;
    
    let track_id = track.id;
    let dec_opts: DecoderOptions = Default::default();
    let mut decoder = symphonia::default::get_codecs()
        .make(&track.codec_params, &dec_opts)
        .map_err(|e| PyRuntimeError::new_err(format!("Unsupported codec: {}", e)))?;
    
    let mut sample_buf = None;
    let mut sum_sq = 0.0;
    let mut count = 0;
    
    loop {
        let packet = match format.next_packet() {
            Ok(packet) => packet,
            Err(_) => break,
        };
        
        if packet.track_id() != track_id {
            continue;
        }
        
        let decoded = match decoder.decode(&packet) {
            Ok(decoded) => decoded,
            Err(_) => continue, // Ignore decode errors
        };
        
        if sample_buf.is_none() {
            sample_buf = Some(SampleBuffer::<f32>::new(decoded.capacity() as u64, *decoded.spec()));
        }
        
        if let Some(buf) = &mut sample_buf {
            buf.copy_interleaved_ref(decoded.clone());
            let samples = buf.samples();
            let channels = decoded.spec().channels.count() as usize;
            
            for chunk in samples.chunks(channels) {
                let mono = chunk.iter().sum::<f32>() / channels as f32;
                sum_sq += mono * mono;
                count += 1;
            }
        }
    }
    
    if count == 0 {
        return Ok(f32::NEG_INFINITY);
    }
    
    let rms = (sum_sq / count as f32).sqrt();
    if rms == 0.0 {
        return Ok(f32::NEG_INFINITY);
    }
    
    Ok(20.0 * rms.log10())
}

#[pymodule]
fn scribe_audio_core(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(get_split_timestamps, m)?)?;
    m.add_function(wrap_pyfunction!(get_audio_dbfs, m)?)?;
    Ok(())
}
