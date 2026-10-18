//! Recovered fixed-score Rust synthesis using the pinned Windows system bank.
//! Native comparison and build pins: artifacts/rust/audio/standalone.json.
extern crate alloc;
pub mod bank;
pub mod data;
pub mod patch_code;
pub mod score_code;
pub mod arp;
pub mod graph;
pub mod effects;
pub mod formants;
pub mod nodes;
pub mod math;
pub mod score;
pub mod voice;
pub mod sources;
pub mod oscillator;
pub mod sequencer;
pub mod glitch;
pub mod runtime;

pub const SAMPLE_RATE: u32 = 44_100;
pub const CHANNELS: usize = 2;
pub const TOTAL_FRAMES: u32 = 19_964_544;
pub const EVENT_QUANTUM: u32 = 64;

#[cold]
fn fatal() -> ! {
    #[cfg(feature="sizecoded")]
    { crate::fatal() }
    #[cfg(not(feature="sizecoded"))]
    { panic!("invalid fixed audio graph") }
}

/// Render every sample of the fixed score; controls and state are private to this call.
pub fn render(output: &mut [f32]) -> Result<(), &'static str> {
    // The sizecoded worker always passes the exact allocation.
    #[cfg(not(feature="sizecoded"))]
    if output.len() != TOTAL_FRAMES as usize * CHANNELS {
        return Err("pcm size");
    }
    runtime::render_prefix(output).map(|_| ())
}
