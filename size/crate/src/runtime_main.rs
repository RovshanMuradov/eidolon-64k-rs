//! Windows runtime candidate; --graphics-diagnostic is explicitly audio-free.
#![cfg_attr(all(feature = "sizecoded", target_os = "windows"), no_std)]
#![cfg_attr(all(feature = "sizecoded", target_os = "windows"), no_main)]

#[cfg(all(feature = "sizecoded", target_os = "windows"))]
#[panic_handler]
fn panic(_: &core::panic::PanicInfo) -> ! { eidolon::fatal() }

#[cfg(all(feature = "sizecoded", target_os = "windows"))]
core::arch::global_asm!(".global _eidolon_entry", "_eidolon_entry:",
    "and esp, -16", "call _eidolon_main", "ud2");

#[cfg(all(feature = "sizecoded", target_os = "windows"))]
#[no_mangle]
pub extern "C" fn eidolon_main() -> ! {
    unsafe { eidolon::minimal::initialize(); }
    #[cfg(all(not(feature = "measure-no-audio"), not(feature = "measure-no-graphics")))]
    let result = eidolon::runtime::run_with_synth(eidolon::audio::render);
    #[cfg(all(feature = "measure-no-audio", not(feature = "measure-no-graphics")))]
    let result = eidolon::runtime::graphics_diagnostic();
    #[cfg(all(feature = "measure-no-graphics", not(feature = "measure-no-audio")))]
    let result = {
        extern crate alloc;
        let mut pcm = alloc::vec![0.0; eidolon::contract::PCM_SAMPLES];
        eidolon::audio::render(&mut pcm)
    };
    #[cfg(all(feature = "measure-no-graphics", feature = "measure-no-audio"))]
    let result: Result<(), &str> = Ok(());
    if let Err(error) = result { report(error) }
    unsafe { eidolon::minimal::exit(0) }
}

#[cfg(all(feature = "sizecoded", target_os = "windows"))]
trait Report { fn report(self) -> !; }
#[cfg(all(feature = "sizecoded", target_os = "windows"))]
impl Report for eidolon::RuntimeError { fn report(self) -> ! { match self {} } }
#[cfg(all(feature = "sizecoded", target_os = "windows"))]
impl Report for &str { fn report(self) -> ! { eidolon::minimal::fail(self) } }
#[cfg(all(feature = "sizecoded", target_os = "windows"))]
fn report(error: impl Report) -> ! { error.report()
}

#[cfg(not(all(feature = "sizecoded", target_os = "windows")))]
fn main() {
    #[cfg(target_os = "windows")]
    {
        let mode = std::env::args().nth(1).unwrap_or_default();
        let result = match mode.as_str() {
            "--graphics-diagnostic" => eidolon::runtime::graphics_diagnostic(),
            "--play" => eidolon::runtime::run_with_synth(eidolon::audio::render),
            _ => { eprintln!("Usage: eidolon-runtime --play | --graphics-diagnostic"); return; }
        };
        if let Err(error) = result { eprintln!("EIDOLON_RUNTIME error: {error}"); std::process::exit(1); }
    }
    #[cfg(not(target_os = "windows"))]
    { eprintln!("The audiovisual runtime requires Windows x86; use eidolon-engine for host CPU checks."); }
}
