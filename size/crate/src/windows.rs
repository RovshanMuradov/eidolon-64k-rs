//! Minimal Win32/WGL/waveOut ABI; native widths are checked at compile time.
#![allow(non_snake_case)]
use core::ffi::{c_char, c_void};
pub type Handle = *mut c_void;
pub type WindowProc = unsafe extern "system" fn(Handle, u32, usize, isize) -> isize;

#[repr(C)]
pub struct WindowClass {
    pub style: u32, pub procedure: WindowProc, pub class_extra: i32, pub window_extra: i32,
    pub instance: Handle, pub icon: Handle, pub cursor: Handle, pub background: Handle,
    pub menu: *const c_char, pub name: *const c_char,
}
#[repr(C)]
#[derive(Default)]
pub struct Rect { pub left: i32, pub top: i32, pub right: i32, pub bottom: i32 }
#[repr(C)]
#[derive(Default)]
pub struct Message {
    pub window: Handle, pub message: u32, pub wparam: usize, pub lparam: isize,
    pub time: u32, pub x: i32, pub y: i32,
}
#[repr(C)]
pub struct PixelFormat {
    pub size: u16, pub version: u16, pub flags: u32,
    pub pixel_type: u8, pub color_bits: u8, pub red_bits: u8, pub red_shift: u8,
    pub green_bits: u8, pub green_shift: u8, pub blue_bits: u8, pub blue_shift: u8,
    pub alpha_bits: u8, pub alpha_shift: u8, pub accum_bits: u8, pub accum_red: u8,
    pub accum_green: u8, pub accum_blue: u8, pub accum_alpha: u8,
    pub depth_bits: u8, pub stencil_bits: u8, pub aux_buffers: u8, pub layer_type: u8,
    pub reserved: u8, pub layer_mask: u32, pub visible_mask: u32, pub damage_mask: u32,
}
impl Default for PixelFormat {
    fn default() -> Self { Self::native() }
}
impl PixelFormat {
    pub const fn native() -> Self {
        // Exact unusual native bytes at 0x440c30: preserve pixel_type=32 and
        // accum_alpha=32 rather than silently moving them to color/depth fields.
        Self { size: 40, version: 1, flags: 0x21, pixel_type: 32, color_bits: 0,
            red_bits: 0, red_shift: 0, green_bits: 0, green_shift: 0, blue_bits: 0, blue_shift: 0,
            alpha_bits: 0, alpha_shift: 0, accum_bits: 0, accum_red: 0, accum_green: 0, accum_blue: 0,
            accum_alpha: 32, depth_bits: 0, stencil_bits: 0, aux_buffers: 0, layer_type: 0,
            reserved: 0, layer_mask: 0, visible_mask: 0, damage_mask: 0 }
    }
}

#[repr(C, packed(2))]
pub struct WaveFormat {
    pub tag: u16, pub channels: u16, pub rate: u32, pub bytes_per_second: u32,
    pub block_align: u16, pub bits: u16, pub extra: u16,
}
#[repr(C)]
pub struct WaveHeader {
    pub data: *mut c_char, pub bytes: u32, pub recorded: u32, pub user: usize,
    pub flags: u32, pub loops: u32, pub next: *mut WaveHeader, pub reserved: usize,
}
#[repr(C)]
pub struct MultimediaTime { pub kind: u32, pub value: [u32; 2] }

const _: () = assert!(size_of::<PixelFormat>() == 40);
const _: () = assert!(size_of::<WaveFormat>() == 18);
const _: () = assert!(size_of::<MultimediaTime>() == 12);
#[cfg(target_pointer_width = "32")]
const _: () = {
    assert!(size_of::<WaveHeader>() == 32);
    assert!(size_of::<Message>() == 28);
    assert!(size_of::<WindowClass>() == 40);
};

#[link(name = "user32")]
#[cfg(not(feature = "hashed-imports"))]
extern "system" {
    pub fn RegisterClassA(class: *const WindowClass) -> u16;
    pub fn CreateWindowExA(ex: u32, class: *const c_char, title: *const c_char, style: u32,
        x: i32, y: i32, width: i32, height: i32, parent: Handle, menu: Handle, instance: Handle, param: Handle) -> Handle;
    pub fn DefWindowProcA(window: Handle, message: u32, wparam: usize, lparam: isize) -> isize;
    pub fn DestroyWindow(window: Handle) -> i32;
    pub fn PostQuitMessage(code: i32);
    pub fn GetClientRect(window: Handle, rect: *mut Rect) -> i32;
    pub fn GetDC(window: Handle) -> Handle;
    pub fn ReleaseDC(window: Handle, dc: Handle) -> i32;
    pub fn PeekMessageA(message: *mut Message, window: Handle, min: u32, max: u32, remove: u32) -> i32;
    pub fn TranslateMessage(message: *const Message) -> i32;
    pub fn DispatchMessageA(message: *const Message) -> isize;
    pub fn GetAsyncKeyState(key: i32) -> i16;
    pub fn ShowCursor(show: i32) -> i32;
}
#[link(name = "gdi32")]
#[cfg(not(feature = "hashed-imports"))]
extern "system" {
    pub fn ChoosePixelFormat(dc: Handle, format: *const PixelFormat) -> i32;
    pub fn SetPixelFormat(dc: Handle, index: i32, format: *const PixelFormat) -> i32;
    pub fn SwapBuffers(dc: Handle) -> i32;
}
#[link(name = "kernel32")]
#[cfg(not(feature = "hashed-imports"))]
extern "system" {
    pub fn GetModuleHandleA(name: *const c_char) -> Handle;
    pub fn GetTickCount() -> u32;
    pub fn Sleep(milliseconds: u32);
    pub fn CreateThread(attributes: Handle, stack_bytes: usize,
        start: unsafe extern "system" fn(Handle) -> u32, parameter: Handle,
        flags: u32, id: *mut u32) -> Handle;
    pub fn WaitForSingleObject(handle: Handle, milliseconds: u32) -> u32;
    pub fn CloseHandle(handle: Handle) -> i32;
    pub fn GetProcessHeap() -> Handle;
    pub fn HeapAlloc(heap: Handle, flags: u32, bytes: usize) -> Handle;
    pub fn HeapFree(heap: Handle, flags: u32, pointer: Handle) -> i32;
    pub fn GetSystemDirectoryA(buffer: *mut u8, capacity: u32) -> u32;
    pub fn CreateFileA(path: *const u8, access: u32, sharing: u32, security: Handle,
        creation: u32, flags: u32, template: Handle) -> Handle;
    pub fn ReadFile(file: Handle, buffer: *mut u8, capacity: u32, read: *mut u32, overlapped: Handle) -> i32;
    pub fn GetStdHandle(kind: u32) -> Handle;
    pub fn WriteFile(file: Handle, buffer: *const u8, bytes: u32, written: *mut u32, overlapped: Handle) -> i32;
}
#[link(name = "opengl32")]
#[cfg(not(feature = "hashed-imports"))]
extern "system" {
    pub fn wglCreateContext(dc: Handle) -> Handle;
    pub fn wglMakeCurrent(dc: Handle, context: Handle) -> i32;
    pub fn wglDeleteContext(context: Handle) -> i32;
    pub fn wglGetProcAddress(name: *const c_char) -> *const c_void;
    pub fn glGenTextures(count: i32, textures: *mut u32);
    pub fn glDeleteTextures(count: i32, textures: *const u32);
    pub fn glBindTexture(target: u32, texture: u32);
    pub fn glTexImage2D(target: u32, level: i32, internal: i32, width: i32, height: i32,
        border: i32, format: u32, kind: u32, pixels: *const c_void);
    pub fn glTexParameteri(target: u32, parameter: u32, value: i32);
    pub fn glGetTexImage(target: u32, level: i32, format: u32, kind: u32, pixels: *mut c_void);
    pub fn glViewport(x: i32, y: i32, width: i32, height: i32);
    pub fn glRecti(x1: i32, y1: i32, x2: i32, y2: i32);
    pub fn glGetString(name: u32) -> *const u8;
}
#[link(name = "winmm")]
#[cfg(not(feature = "hashed-imports"))]
extern "system" {
    pub fn waveOutOpen(handle: *mut Handle, device: u32, format: *const WaveFormat,
        callback: usize, instance: usize, flags: u32) -> u32;
    pub fn waveOutPrepareHeader(handle: Handle, header: *mut WaveHeader, bytes: u32) -> u32;
    pub fn waveOutWrite(handle: Handle, header: *mut WaveHeader, bytes: u32) -> u32;
    pub fn waveOutGetPosition(handle: Handle, time: *mut MultimediaTime, bytes: u32) -> u32;
    pub fn waveOutReset(handle: Handle) -> u32;
    pub fn waveOutUnprepareHeader(handle: Handle, header: *mut WaveHeader, bytes: u32) -> u32;
    pub fn waveOutClose(handle: Handle) -> u32;
}

#[cfg(feature = "hashed-imports")]
include!(concat!(env!("OUT_DIR"), "/hashed_imports.rs"));

/// Read only the platform DLS bank; no search in the working directory.
#[no_mangle]
pub unsafe extern "C" fn eidolon_read_gm_dls(dst: *mut u8, capacity: u32) -> u32 {
    let mut path = [0u8; 280];
    let n = GetSystemDirectoryA(path.as_mut_ptr(), 260) as usize;
    if n == 0 || n >= 260 { return 0; }
    let suffix = b"\\drivers\\gm.dls\0";
    path[n..n + suffix.len()].copy_from_slice(suffix);
    let file = CreateFileA(path.as_ptr(), 0x80000000, 1, core::ptr::null_mut(), 3, 0, core::ptr::null_mut());
    if file as usize == usize::MAX { return 0; }
    let mut bytes = 0;
    let ok = ReadFile(file, dst, capacity, &mut bytes, core::ptr::null_mut());
    CloseHandle(file);
    if ok != 0 { bytes } else { 0 }
}
