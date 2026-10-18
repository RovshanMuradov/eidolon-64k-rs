//! CPU-only adapter for the size crate, built by verify_audio.py.
#![allow(dead_code)]
#[path = "../crate/src/audio/mod.rs"]
mod audio;

use std::{io::Write, sync::OnceLock};

static BANK: OnceLock<Vec<u8>> = OnceLock::new();

pub fn fatal() -> ! { panic!("invalid fixed audio graph") }

#[no_mangle]
pub unsafe extern "C" fn eidolon_read_gm_dls(dst: *mut u8, capacity: u32) -> u32 {
    let data = BANK.get().expect("bank initialized");
    let count = data.len().min(capacity as usize);
    core::ptr::copy_nonoverlapping(data.as_ptr(), dst, count);
    count as u32
}

fn main() {
    let args: Vec<_> = std::env::args_os().collect();
    assert_eq!(args.len(), 3, "usage: render_pcm BANK OUTPUT");
    // These are safe public slice APIs even with sizecoded enabled. The worker
    // uses the exact allocation, but a caller must not be able to cause an
    // out-of-bounds 64-frame write by passing a short/non-quantized slice.
    assert_eq!(audio::render(&mut []), Err("pcm size"));
    assert_eq!(audio::render(&mut [0.0; 128]), Err("pcm size"));
    assert_eq!(audio::runtime::render_prefix(&mut []), Err("prefix"));
    assert_eq!(audio::runtime::render_prefix(&mut [0.0; 129]), Err("prefix"));
    BANK.set(std::fs::read(&args[1]).expect("read bank")).unwrap();
    // A poison value also detects unwritten samples in the full allocation.
    let mut pcm = vec![f32::from_bits(0x7fc01234); audio::TOTAL_FRAMES as usize * audio::CHANNELS];
    audio::render(&mut pcm).expect("complete render");
    let mut output = std::io::BufWriter::new(std::fs::File::create(&args[2]).expect("create PCM"));
    for sample in pcm {
        output.write_all(&sample.to_le_bytes()).expect("write PCM");
    }
    output.flush().expect("flush PCM");
    println!("rendered {} stereo frames", audio::TOTAL_FRAMES);
}
