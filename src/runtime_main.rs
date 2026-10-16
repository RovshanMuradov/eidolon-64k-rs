//! Windows runtime candidate; --graphics-diagnostic is explicitly audio-free.
fn main() {
    #[cfg(target_os = "windows")]
    {
        let mode = std::env::args().nth(1).unwrap_or_default();
        let result = match mode.as_str() {
            "--graphics-diagnostic" => eidolon::runtime::graphics_diagnostic(),
            "--play" => {
                // Keep the runtime/ABI linkable while T23 completes its separately owned module.
                // The failure is explicit; this branch never substitutes silence as successful PCM.
                let render = std::hint::black_box(incomplete_synth as eidolon::runtime::RenderPcm);
                eidolon::runtime::run_with_synth(render)
            }
            _ => { eprintln!("Usage: eidolon-runtime --graphics-diagnostic | --play (synth integration pending)"); return; }
        };
        if let Err(error) = result { eprintln!("EIDOLON_RUNTIME error: {error}"); std::process::exit(1); }
    }
    #[cfg(not(target_os = "windows"))]
    { eprintln!("The audiovisual runtime requires Windows x86; use eidolon-engine for host CPU checks."); }
}

#[cfg(target_os = "windows")]
fn incomplete_synth(_: &mut [f32]) -> Result<(), &'static str> {
    Err("T23 standalone synthesizer is not integrated; no PCM submitted")
}
