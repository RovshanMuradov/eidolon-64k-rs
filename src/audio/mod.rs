//! Recovered fixed-score audio slices. Whole graph rendering is not yet ported.
//! Source pin and verification scope: artifacts/rust/audio/slices.json.
pub mod data;
pub mod arp;
pub mod graph;
pub mod nodes;
pub mod math;
pub mod score;
pub mod voice;

pub const SAMPLE_RATE: u32 = 44_100;
pub const CHANNELS: usize = 2;
pub const TOTAL_FRAMES: u32 = 19_964_544;
pub const EVENT_QUANTUM: u32 = 64;

/// Contract entrypoint. No playable output until graph/voice/effect ports are complete.
pub fn render(output: &mut [f32]) -> Result<(), &'static str> {
    if output.len() != TOTAL_FRAMES as usize * CHANNELS {
        return Err("audio output must contain exactly 39929088 samples");
    }
    Err("Rust graph/voice/effect renderer is not yet complete")
}
