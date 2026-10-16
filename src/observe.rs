//! Synchronous capture ABI; exporting a marker is not evidence of a runtime capture.
use crate::{contract::Clock, engine::Frame, physics::Record};

#[repr(C)]
#[derive(Clone, Copy)]
pub struct RuntimeSnapshot {
    pub frame_index: u32,
    pub cursor: u32,
    pub seconds_bits: u32,
    pub beat_bits: u32,
    pub row: u32,
    pub local_beat_bits: u32,
    pub dt_bits: u32,
    pub records: [Record; 4],
}
const _: () = assert!(size_of::<RuntimeSnapshot>() == 284);

impl RuntimeSnapshot {
    pub fn frame(index: u32, frame: &Frame, records: [Record; 4]) -> Self {
        Self { frame_index: index, cursor: frame.clock.cursor, seconds_bits: frame.clock.seconds.to_bits(),
            beat_bits: frame.clock.beat.to_bits(), row: frame.row.index as u32,
            local_beat_bits: frame.local_beat.to_bits(), dt_bits: frame.dt.to_bits(), records }
    }
    pub fn endpoint(index: u32, clock: Clock, previous_seconds: f32, records: [Record; 4]) -> Self {
        Self { frame_index: index, cursor: clock.cursor, seconds_bits: clock.seconds.to_bits(),
            beat_bits: clock.beat.to_bits(), row: u32::MAX, local_beat_bits: 0,
            dt_bits: (clock.seconds - previous_seconds).to_bits(), records }
    }
}

/// cdecl export in eidolon-runtime.exe. Payload is borrowed only for this call.
/// Kinds1..5: RuntimeSnapshot; kinds6/7: complete interleaved PCM bytes.
#[no_mangle]
#[inline(never)]
pub extern "C" fn eidolon_runtime_event(kind: u32, data: *const u8, bytes: u32) {
    std::hint::black_box((kind, data, bytes));
}

pub fn snapshot(kind: u32, state: &RuntimeSnapshot) {
    eidolon_runtime_event(kind, std::ptr::from_ref(state).cast(), size_of::<RuntimeSnapshot>() as u32);
}
pub fn pcm(kind: u32, samples: &[f32]) {
    eidolon_runtime_event(kind, samples.as_ptr().cast(), std::mem::size_of_val(samples) as u32);
}
