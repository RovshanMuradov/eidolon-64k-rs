fn main() {
    println!("cargo:rerun-if-changed=build.rs");
    if std::env::var_os("CARGO_FEATURE_HASHED_IMPORTS").is_some() { hashed_imports(); }
    if std::env::var_os("CARGO_FEATURE_SAMPLE_DELTA").is_some() {
        sample_delta();
    }
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows") {
        if std::env::var_os("CARGO_FEATURE_SIZECODED").is_some() {
            for arg in ["-nostartfiles", "-Wl,--entry=_eidolon_entry", "-Wl,--subsystem,windows", "-Wl,--stack,2097152", "-Wl,--disable-dynamicbase"] {
                println!("cargo:rustc-link-arg-bin=eidolon-runtime={arg}");
            }
        }
        let path = std::path::PathBuf::from(std::env::var_os("OUT_DIR").unwrap()).join("runtime.def");
        std::fs::write(&path, "EXPORTS\n    eidolon_runtime_event\n").unwrap();
        println!("cargo:rustc-link-arg-bin=eidolon-runtime={}", path.display());
    }
}

fn hashed_imports() {
    use std::fmt::Write;
    println!("cargo:rerun-if-changed=src/windows.rs");
    let source = std::fs::read_to_string("src/windows.rs").unwrap();
    let mut wrappers = String::new();
    let mut records = String::new();
    let mut count = 0;
    for block in source.split("#[link(name = \"").skip(1) {
        let dll = block.split_once('"').unwrap().0;
        let body = block.split_once("extern \"system\" {").unwrap().1.split_once('}').unwrap().0;
        for item in body.split("pub fn ").skip(1) {
            let signature = item.split_once(';').unwrap().0;
            let (name, rest) = signature.split_once('(').unwrap();
            let (parameters, result) = rest.rsplit_once(')').unwrap();
            let mut depth = 0;
            let mut begin = 0;
            let mut names = Vec::new();
            let mut types = Vec::new();
            for (i, c) in parameters.char_indices().chain([(parameters.len(), ',')]) {
                match c { '(' => depth += 1, ')' => depth -= 1, _ => () }
                if c == ',' && depth == 0 {
                    let parameter = parameters[begin..i].trim();
                    if !parameter.is_empty() {
                        let (n, t) = parameter.split_once(':').unwrap();
                        names.push(n.trim()); types.push(t.trim());
                    }
                    begin = i + 1;
                }
            }
            let hash = name.bytes().fold(2166136261u32, |h, b| (h ^ b as u32).wrapping_mul(16777619));
            writeln!(records, "(b\"{dll}.dll\\0\".as_ptr(), {hash}),").unwrap();
            writeln!(wrappers, "pub unsafe fn {signature} {{ let f = core::mem::transmute::<usize, unsafe extern \"system\" fn({}){result}>(IMPORTS[{count}]); f({}) }}", types.join(","), names.join(",")).unwrap();
            count += 1;
        }
    }
    let generated = format!("static mut IMPORTS: [usize; {count}] = [0; {count}];\npub unsafe fn initialize_imports() {{ for (i, (dll, hash)) in [{records}].into_iter().enumerate() {{ IMPORTS[i] = crate::minimal::resolve(dll, hash); }} }}\n{wrappers}");
    let path = std::path::PathBuf::from(std::env::var_os("OUT_DIR").unwrap()).join("hashed_imports.rs");
    std::fs::write(path, generated).unwrap();
}

fn sample_delta() {
    use std::fmt::Write;
    println!("cargo:rerun-if-changed=src/audio/data.rs");
    let original = std::fs::read_to_string("src/audio/data.rs").unwrap();
    let start = original.find("pub static WAVE_").unwrap();
    let mut generated = original[..start].to_owned();
    let mut names = Vec::new();
    for block in original[start..].split("pub static WAVE_").skip(1) {
        let (name, body) = block.split_once(": &[i16] = &[").unwrap();
        let values: Vec<i16> = body.split_once("];").unwrap().0
            .split(',').filter(|v| !v.trim().is_empty())
            .map(|v| v.trim().parse().unwrap()).collect();
        let mut previous = 0u16;
        let residuals: Vec<u16> = values.iter().map(|&value| {
            let word = value as u16;
            let delta = word.wrapping_sub(previous);
            previous = word;
            delta
        }).collect();
        writeln!(generated, "pub static WAVE_{name}: &[u8] = &[").unwrap();
        for shift in [0, 8] {
            for (i, &value) in residuals.iter().enumerate() {
                write!(generated, "{},", (value >> shift) as u8).unwrap();
                if i % 32 == 31 { generated.push('\n'); }
            }
        }
        generated.push_str("\n];\n");
        names.push(name.to_owned());
    }
    generated.push_str("pub static WAVES: &[(u16, &[u8])] = &[\n");
    for name in names { writeln!(generated, "({name}, WAVE_{name}),").unwrap(); }
    generated.push_str("];\n");
    let path = std::path::PathBuf::from(std::env::var_os("OUT_DIR").unwrap()).join("audio_delta.rs");
    std::fs::write(path, generated).unwrap();
}
