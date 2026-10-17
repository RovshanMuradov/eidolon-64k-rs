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
#[cfg(not(all(feature = "sizecoded", target_arch = "x86", target_os = "windows")))]
#[no_mangle]
#[inline(never)]
pub extern "C" fn eidolon_runtime_event(kind: u32, data: *const u8, bytes: u32) {
    core::hint::black_box((kind, data, bytes));
}
// Capture ABI: the verifier patches the fixed 7-byte prologue 55 89 e5 56 83 ec 0c, independent
// of whether the rest of the program keeps frame pointers.
#[cfg(all(feature = "sizecoded", target_arch = "x86", target_os = "windows"))]
core::arch::global_asm!(
    ".globl _eidolon_runtime_event",
    "_eidolon_runtime_event:",
    "push ebp", "mov ebp, esp", "push esi", "sub esp, 12",
    "add esp, 12", "pop esi", "pop ebp", "ret",
);
#[cfg(all(feature = "sizecoded", target_arch = "x86", target_os = "windows"))]
extern "C" { pub fn eidolon_runtime_event(kind: u32, data: *const u8, bytes: u32); }

#[allow(unused_unsafe)]
pub fn snapshot(kind: u32, state: &RuntimeSnapshot) {
    unsafe { eidolon_runtime_event(kind, core::ptr::from_ref(state).cast(), size_of::<RuntimeSnapshot>() as u32); }
}
#[allow(unused_unsafe)]
pub fn pcm(kind: u32, samples: &[f32]) {
    unsafe { eidolon_runtime_event(kind, samples.as_ptr().cast(), core::mem::size_of_val(samples) as u32); }
}
