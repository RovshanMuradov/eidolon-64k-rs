fn main() {
    println!("cargo:rerun-if-changed=build.rs");
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows") {
        let path = std::path::PathBuf::from(std::env::var_os("OUT_DIR").unwrap()).join("runtime.def");
        std::fs::write(&path, "EXPORTS\n    eidolon_runtime_event\n").unwrap();
        println!("cargo:rustc-link-arg-bin=eidolon-runtime={}", path.display());
    }
}
