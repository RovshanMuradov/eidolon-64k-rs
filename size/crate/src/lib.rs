//! Recovered engine slice. Native runtime equivalence is a separate validation gate.
#![cfg_attr(all(feature = "sizecoded", target_os = "windows"), no_std)]
extern crate alloc;
/// Sizecoded Windows errors are fail-fast: constructing one prints
/// "EIDOLON_RUNTIME error: <msg>" and exits 1, so Result plumbing compiles away.
#[cfg(all(feature = "sizecoded", target_os = "windows"))]
pub enum RuntimeError {}
#[cfg(all(feature = "sizecoded", target_os = "windows"))]
impl From<&'static str> for RuntimeError {
    #[inline(always)]
    fn from(message: &'static str) -> Self { minimal::fail(message) }
}
#[cfg(not(all(feature = "sizecoded", target_os = "windows")))]
pub type RuntimeError = alloc::string::String;
#[cfg(all(feature = "sizecoded", target_os = "windows"))]
pub mod minimal;
#[cfg(all(feature = "sizecoded", target_os = "windows"))]
mod minimal_memory;

pub fn fatal() -> ! {
    #[cfg(all(feature = "sizecoded", target_os = "windows"))]
    unsafe { minimal::exit(1) }
    #[cfg(not(all(feature = "sizecoded", target_os = "windows")))]
    std::process::abort()
}
pub mod assets;
#[cfg(feature = "fixed-core")]
pub mod fixed;
#[cfg(feature = "compact-graphics")]
pub mod compact_graphics;
/// GL uniform names matching the embedded shaders (renamed in compact CG29 blobs).
#[cfg(feature = "compact-graphics")]
pub mod gl_names;
#[cfg(not(feature = "compact-graphics"))]
#[path = "gl_names_original.rs"]
pub mod gl_names;
pub mod audio;
pub mod contract;
pub mod engine;
pub mod fp;
pub mod physics;
pub mod timeline;
pub mod observe;
pub mod synthesis;
#[cfg(target_os = "windows")]
pub mod runtime;
#[cfg(target_os = "windows")]
mod windows;
#[cfg(target_os = "windows")]
mod graphics;

#[cfg(test)]
mod checks;
