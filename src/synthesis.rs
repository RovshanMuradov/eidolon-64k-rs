//! Engine-owned PCM allocation/thread seam shared by playback and CPU diagnostics.
use crate::{audio, contract};
use std::thread;

pub type RenderPcm = fn(&mut [f32]) -> Result<(), &'static str>;
pub type Worker = thread::JoinHandle<Result<Vec<f32>, String>>;

const _: () = {
    assert!(audio::SAMPLE_RATE == contract::SAMPLE_RATE);
    assert!(audio::CHANNELS == contract::CHANNELS);
    assert!(audio::TOTAL_FRAMES as usize == contract::PCM_FRAMES);
};

/// Only a successful complete render returns its allocation to the playback thread.
pub fn spawn(render: RenderPcm) -> Result<Worker, String> {
    thread::Builder::new().name("eidolon-synth".into()).spawn(move || {
        let mut pcm = vec![0.0_f32; contract::PCM_SAMPLES];
        render(&mut pcm).map_err(str::to_owned)?;
        Ok(pcm)
    }).map_err(|error| format!("could not start synthesis worker: {error}"))
}
