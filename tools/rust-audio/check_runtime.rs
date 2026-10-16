#[path="../../src/audio/mod.rs"]
mod audio;
#[cfg(target_arch="x86_64")]
#[allow(deprecated)]
use core::arch::x86_64::{_mm_getcsr,_mm_setcsr};

#[allow(deprecated)]
fn render_with_control(control:u32)->Vec<u32> {
    unsafe { _mm_setcsr(control); }
    let before=unsafe { _mm_getcsr() };
    let mut pcm=vec![f32::from_bits(0x7fc01234);262144*2];
    let stats=audio::runtime::render_prefix(&mut pcm).unwrap();
    assert_eq!(stats.final_tick,262145);
    assert_eq!(unsafe { _mm_getcsr() },before,"caller MXCSR must be restored exactly");
    assert!(pcm.iter().all(|v|v.to_bits()!=0x7fc01234));
    pcm.into_iter().map(f32::to_bits).collect()
}
#[allow(deprecated)]
fn main() {
    let original=unsafe { _mm_getcsr() };
    let mut bad=[f32::from_bits(0x7fc01234);8];
    assert!(audio::render(&mut bad).is_err());
    assert!(audio::runtime::render_prefix(&mut bad).is_err());
    assert!(bad.iter().all(|v|v.to_bits()==0x7fc01234));
    assert_eq!(unsafe { _mm_getcsr() },original);
    let first=render_with_control(0x1f80);
    let second=render_with_control(0x3f80);
    assert_eq!(first,second,"fresh graph/RNG state on repeat and private FP controls");
    let left=std::thread::spawn(||render_with_control(0x5f80));
    let right=std::thread::spawn(||render_with_control(0x7f80));
    assert_eq!(left.join().unwrap(),first);
    assert_eq!(right.join().unwrap(),first);
    unsafe { _mm_setcsr(original); }
    println!("PASS invalid-size/no-write, full-write, repeat-reset, concurrent-isolation, exact-MXCSR-restoration");
}
