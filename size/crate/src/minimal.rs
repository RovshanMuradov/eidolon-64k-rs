//! CRT-free Win32 allocator and process exit for the sizecoded executable.
use core::alloc::{GlobalAlloc, Layout};
use crate::windows::{GetProcessHeap, HeapAlloc, HeapFree};

#[link(name = "kernel32")]
extern "system" {
    fn ExitProcess(code: u32) -> !;
}

pub unsafe fn initialize() {
    #[cfg(feature = "hashed-imports")]
    crate::windows::initialize_imports();
}

#[cfg(feature = "hashed-imports")]
pub unsafe fn resolve(module: *const u8, wanted: u32) -> usize {
    #[link(name = "kernel32")]
    extern "system" {
        fn LoadLibraryA(name: *const u8) -> *const u8;
        fn GetProcAddress(module: *const u8, name: *const u8) -> usize;
    }
    // Windows' loader handles forwarded exports through GetProcAddress after the
    // matching name is found; no forwarding assumptions about Wine/kernelbase.
    let base = LoadLibraryA(module);
    if base.is_null() { exit(1); }
    let pe = base.add(base.add(60).cast::<u32>().read_unaligned() as usize);
    let export = base.add(pe.add(120).cast::<u32>().read_unaligned() as usize);
    let count = export.add(24).cast::<u32>().read_unaligned() as usize;
    let names = base.add(export.add(32).cast::<u32>().read_unaligned() as usize).cast::<u32>();
    for i in 0..count {
        let name = base.add(names.add(i).read_unaligned() as usize);
        let mut p = name;
        let mut hash = 2166136261u32;
        while *p != 0 { hash = (hash ^ *p as u32).wrapping_mul(16777619); p = p.add(1); }
        if hash == wanted {
            let address = GetProcAddress(base, name);
            if address == 0 { exit(1); }
            return address;
        }
    }
    exit(1)
}

struct Heap;
impl Heap {
    unsafe fn allocate(layout: Layout, flags: u32) -> *mut u8 {
        let align = layout.align().max(size_of::<usize>());
        let Some(bytes) = layout.size().checked_add(align) else { return core::ptr::null_mut() };
        let base = HeapAlloc(GetProcessHeap(), flags, bytes) as *mut u8;
        if base.is_null() { return base; }
        let aligned = ((base as usize + align) & !(align - 1)) as *mut u8;
        aligned.cast::<*mut u8>().sub(1).write(base);
        aligned
    }
}
unsafe impl GlobalAlloc for Heap {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 { Self::allocate(layout, 0) }
    #[cfg(feature = "zero-heap")]
    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 { Self::allocate(layout, 8) }
    unsafe fn dealloc(&self, pointer: *mut u8, _: Layout) {
        HeapFree(GetProcessHeap(), 0, pointer.cast::<*mut u8>().sub(1).read().cast());
    }
}
#[global_allocator]
static ALLOCATOR: Heap = Heap;

pub unsafe fn exit(code: u32) -> ! { ExitProcess(code) }

#[cold]
#[inline(never)]
pub fn fail(text: &str) -> ! {
    message("EIDOLON_RUNTIME error: "); message(text); message("\n");
    unsafe { exit(1) }
}

pub fn message(text: &str) {
    message_bytes(text.as_bytes());
}
pub fn message_bytes(text: &[u8]) {
    unsafe {
        let mut written = 0;
        crate::windows::WriteFile(crate::windows::GetStdHandle(-12i32 as u32), text.as_ptr(),
            text.len() as u32, &mut written, core::ptr::null_mut());
    }
}

pub fn decimal(mut value: u32) {
    let mut bytes = [0u8; 10];
    let mut i = bytes.len();
    loop {
        i -= 1; bytes[i] = b'0' + (value % 10) as u8; value /= 10;
        if value == 0 { break; }
    }
    message(unsafe { core::str::from_utf8_unchecked(&bytes[i..]) });
}

pub fn endpoint(queries: u32, frames: u32, cursor: u32) {
    message("EIDOLON_RUNTIME mode=playback reason=natural_exit queries="); decimal(queries);
    message(" frames="); decimal(frames);
    message(" terminal_cursor="); decimal(cursor); message("\n");
}

#[no_mangle]
pub extern "C" fn rust_eh_personality() {}
