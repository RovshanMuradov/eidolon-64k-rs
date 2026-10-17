//! Windows runtime candidate; --graphics-diagnostic is explicitly audio-free.
fn main() {
    #[cfg(target_os = "windows")]
    {
        let mode = std::env::args().nth(1).unwrap_or_default();
        let result = match mode.as_str() {
            "--graphics-diagnostic" => eidolon::runtime::graphics_diagnostic(),
            "--play" => eidolon::runtime::run_with_synth(eidolon::audio::render),
            "--capture" => match std::env::args().nth(2) {
                Some(path) => eidolon::runtime::capture(&path),
                None => Err("--capture requires an output path".into()),
            },
            _ => { eprintln!("Usage: eidolon-runtime --play | --capture FRAMES.txt | --graphics-diagnostic"); return; }
        };
        if let Err(error) = result { eprintln!("EIDOLON_RUNTIME error: {error}"); std::process::exit(1); }
    }
    #[cfg(not(target_os = "windows"))]
    { eprintln!("The audiovisual runtime requires Windows x86; use eidolon-engine for host CPU checks."); }
}
