use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use std::fs::File;
use symphonia::core::codecs::audio::AudioDecoderOptions;
use symphonia::core::formats::probe::Hint;
use symphonia::core::formats::{FormatOptions, TrackType};
use symphonia::core::io::MediaSourceStream;
use symphonia::core::meta::MetadataOptions;

fn bounded_chunk_endpoints(candidate_points_ms: &[u32], duration_ms: u32, cap_ms: u32) -> Vec<u32> {
    if duration_ms == 0 || cap_ms == 0 {
        return Vec::new();
    }

    let mut candidates: Vec<u32> = candidate_points_ms
        .iter()
        .copied()
        .filter(|point| *point > 0 && *point < duration_ms)
        .collect();
    candidates.sort_unstable();
    candidates.dedup();

    let mut endpoints = Vec::new();
    let mut chunk_start_ms = 0;
    while duration_ms - chunk_start_ms > cap_ms {
        let hard_limit_ms = chunk_start_ms.saturating_add(cap_ms);
        let useful_floor_ms = chunk_start_ms.saturating_add(cap_ms / 2);
        let chunk_end_ms = candidates
            .iter()
            .copied()
            .filter(|point| *point >= useful_floor_ms && *point <= hard_limit_ms)
            .max()
            .unwrap_or(hard_limit_ms);
        endpoints.push(chunk_end_ms);
        chunk_start_ms = chunk_end_ms;
    }
    endpoints.push(duration_ms);
    endpoints
}

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

/// Find bounded chunk end timestamps in milliseconds, preferring useful silence points.
#[pyfunction]
#[pyo3(signature = (file_path, min_silence_ms, silence_thresh_db, max_duration_ms))]
fn get_split_timestamps(
    file_path: &str,
    min_silence_ms: u32,
    silence_thresh_db: f32,
    max_duration_ms: u32,
) -> PyResult<Vec<u32>> {
    if max_duration_ms == 0 {
        return Err(PyRuntimeError::new_err(
            "max_duration_ms must be greater than zero",
        ));
    }

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

    let mut format = symphonia::default::get_probe()
        .probe(&hint, mss, fmt_opts, meta_opts)
        .map_err(|e| PyRuntimeError::new_err(format!("Unsupported format: {}", e)))?;

    let track = format
        .default_track(TrackType::Audio)
        .ok_or_else(|| PyRuntimeError::new_err("No audio track found"))?;

    let track_id = track.id;
    let audio_params = track
        .codec_params
        .as_ref()
        .and_then(|params| params.audio())
        .ok_or_else(|| PyRuntimeError::new_err("Audio codec parameters are missing"))?;
    let sample_rate = audio_params.sample_rate.unwrap_or(16_000) as usize;

    let dec_opts: AudioDecoderOptions = Default::default();
    let mut decoder = symphonia::default::get_codecs()
        .make_audio_decoder(audio_params, &dec_opts)
        .map_err(|e| PyRuntimeError::new_err(format!("Unsupported codec: {}", e)))?;

    let mut samples = Vec::<f32>::new();

    // We will process audio in ~10ms windows
    let window_size_samples = sample_rate / 100;
    let mut current_window = Vec::with_capacity(window_size_samples);

    let mut current_ms: f64 = 0.0;

    let mut silence_start_ms: Option<f64> = None;
    let mut silence_points = Vec::new();

    loop {
        let packet = match format.next_packet() {
            Ok(Some(packet)) => packet,
            Ok(None) => break,
            Err(symphonia::core::errors::Error::IoError(e))
                if e.kind() == std::io::ErrorKind::UnexpectedEof =>
            {
                break; // End of file
            }
            Err(e) => {
                return Err(PyRuntimeError::new_err(format!(
                    "Failed to read audio packet: {e}"
                )));
            }
        };

        if packet.track_id != track_id {
            continue;
        }

        let decoded = match decoder.decode(&packet) {
            Ok(decoded) => decoded,
            Err(symphonia::core::errors::Error::IoError(e))
                if e.kind() == std::io::ErrorKind::UnexpectedEof =>
            {
                break;
            }
            Err(symphonia::core::errors::Error::DecodeError(e)) => {
                return Err(PyRuntimeError::new_err(format!(
                    "Failed to decode audio packet: {e}"
                )));
            }
            Err(e) => {
                return Err(PyRuntimeError::new_err(format!(
                    "Failed to decode audio: {e}"
                )));
            }
        };

        let channels = decoded.num_planes();
        if channels == 0 {
            continue;
        }
        decoded.copy_to_vec_interleaved(&mut samples);

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

                            silence_points.push(split_point as u32);
                        }
                    }
                    silence_start_ms = None;
                }

                current_ms += window_ms;
                current_window.clear();
            }
        }
    }

    Ok(bounded_chunk_endpoints(
        &silence_points,
        current_ms as u32,
        max_duration_ms,
    ))
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

    let mut format = symphonia::default::get_probe()
        .probe(&hint, mss, fmt_opts, meta_opts)
        .map_err(|e| PyRuntimeError::new_err(format!("Unsupported format: {}", e)))?;

    let track = format
        .default_track(TrackType::Audio)
        .ok_or_else(|| PyRuntimeError::new_err("No audio track found"))?;

    let track_id = track.id;
    let audio_params = track
        .codec_params
        .as_ref()
        .and_then(|params| params.audio())
        .ok_or_else(|| PyRuntimeError::new_err("Audio codec parameters are missing"))?;
    let dec_opts: AudioDecoderOptions = Default::default();
    let mut decoder = symphonia::default::get_codecs()
        .make_audio_decoder(audio_params, &dec_opts)
        .map_err(|e| PyRuntimeError::new_err(format!("Unsupported codec: {}", e)))?;

    let mut samples = Vec::<f32>::new();
    let mut sum_sq = 0.0;
    let mut count = 0;

    loop {
        let packet = match format.next_packet() {
            Ok(Some(packet)) => packet,
            Ok(None) => break,
            Err(symphonia::core::errors::Error::IoError(e))
                if e.kind() == std::io::ErrorKind::UnexpectedEof =>
            {
                break;
            }
            Err(e) => {
                return Err(PyRuntimeError::new_err(format!(
                    "Failed to read audio packet: {e}"
                )));
            }
        };

        if packet.track_id != track_id {
            continue;
        }

        let decoded = match decoder.decode(&packet) {
            Ok(decoded) => decoded,
            Err(symphonia::core::errors::Error::IoError(e))
                if e.kind() == std::io::ErrorKind::UnexpectedEof =>
            {
                break;
            }
            Err(symphonia::core::errors::Error::DecodeError(e)) => {
                return Err(PyRuntimeError::new_err(format!(
                    "Failed to decode audio packet: {e}"
                )));
            }
            Err(e) => {
                return Err(PyRuntimeError::new_err(format!(
                    "Failed to decode audio: {e}"
                )));
            }
        };

        let channels = decoded.num_planes();
        if channels == 0 {
            continue;
        }
        decoded.copy_to_vec_interleaved(&mut samples);

        for chunk in samples.chunks(channels) {
            let mono = chunk.iter().sum::<f32>() / channels as f32;
            sum_sq += mono * mono;
            count += 1;
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
fn scribe_audio_core(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(get_split_timestamps, m)?)?;
    m.add_function(wrap_pyfunction!(get_audio_dbfs, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::bounded_chunk_endpoints;

    #[test]
    fn hard_caps_audio_without_silence() {
        assert_eq!(
            bounded_chunk_endpoints(&[], 130_000, 60_000),
            vec![60_000, 120_000, 130_000]
        );
    }

    #[test]
    fn prefers_useful_silence_and_ignores_invalid_points() {
        assert_eq!(
            bounded_chunk_endpoints(
                &[5_000, 40_000, 90_000, 130_000, 130_000, 140_000],
                130_000,
                60_000,
            ),
            vec![40_000, 90_000, 130_000]
        );
    }
}
