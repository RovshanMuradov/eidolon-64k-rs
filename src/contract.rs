//! Shared PCM and clock contract; synthesis is owned by src/audio/.
pub const SAMPLE_RATE: u32 = 44_100;
pub const CHANNELS: usize = 2;
pub const PCM_FRAMES: usize = 19_964_544;
pub const PCM_SAMPLES: usize = PCM_FRAMES * CHANNELS;
pub const PCM_BYTES: usize = PCM_SAMPLES * size_of::<f32>();
pub const CONTROLLED_STEP: u32 = 735;
pub const PRESENTED_FRAMES: u32 = 27_000;

#[derive(Clone, Copy, Debug)]
pub struct Clock {
    pub cursor: u32,
    pub seconds: f32,
    pub beat: f32,
}

impl Clock {
    pub fn from_samples(cursor: u32) -> Self {
        // Separate native conversion/division/multiply rounding points.
        let seconds = (cursor as f32) / (SAMPLE_RATE as f32);
        let beat = seconds * (80.0_f32 / 60.0_f32);
        Self { cursor, seconds, beat }
    }
}
