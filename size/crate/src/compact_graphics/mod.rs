//! CG29 tables and shared GLSL fragments; T30 compact decoder for modes 0/1/2/7.
//! Build with EIDOLON_COMPACT_GRAPHICS_BLOB=<blob>/graphics.cg29 (tools/optimize/curves/blob.py).
//! Mode 7 (curve pool + descriptors): live curve words are bit-exact; the never-read tin of
//! key 0 and tout of the last key are +0.0; one contiguous pool block per unique curve.
extern crate alloc;
use alloc::{vec, vec::Vec};

static BLOB: &[u8] = include_bytes!(env!("EIDOLON_COMPACT_GRAPHICS_BLOB"));
pub const TABLE_COUNT: usize = 12;
pub const PROGRAM_COUNT: usize = 30;
pub const CURVE_POOL: usize = 0;
pub const FRAMEBUFFERS: usize = 1;
pub const PASS_INPUTS: usize = 2;
pub const PASS_ROUTES: usize = 3;
pub const PASS_STATIC_UNIFORM_VIEWS: usize = 4;
pub const PHYSICS_CONSTANTS: usize = 5;
pub const PROGRAM_RECIPES: usize = 6;
pub const SCENE_PASS_LISTS: usize = 7;
pub const TIMELINE_RANGES: usize = 8;
pub const TIMELINE_TOKENS: usize = 9;
pub const TIMELINE_TRACK_RANGES: usize = 10;
pub const UNIFORM_DESCRIPTORS: usize = 11;

static mut TABLES: [&[u8]; TABLE_COUNT] = [&[]; TABLE_COUNT];
static mut SOURCES: [&[&str]; PROGRAM_COUNT + 1] = [&[]; PROGRAM_COUNT + 1];
static mut READY: bool = false;

#[inline(always)]
fn at(i: usize) -> u8 { unsafe { *BLOB.as_ptr().add(i) } }

fn uint(pos: &mut usize) -> u32 {
    let mut value = 0u32;
    let mut shift = 0u32;
    loop {
        let byte = at(*pos);
        *pos += 1;
        value |= ((byte & 127) as u32).wrapping_shl(shift);
        if byte < 128 { return value; }
        shift += 7;
    }
}

fn ord(bits: u32) -> i32 { let i = bits as i32; if i >= 0 { i } else { -(i & 0x7fffffff) - 1 } }
fn unord(o: i32) -> u32 { if o >= 0 { o as u32 } else { (!o) as u32 | 0x8000_0000 } }

/// Mode 7 streams: lengths(6 x u16) | track | ref | count | time(BE) | val(BE, sorted by
/// uniform*4+component, then first use) | sel | raw. Pool blocks follow first use.
/// Predictions are f32 SSE arithmetic under the default MXCSR set by GraphicsFp at startup.
unsafe fn timeline(pos: usize, pool: *mut u32, desc: *mut u32, tracks: usize) {
    let h = BLOB.as_ptr().add(pos);
    let len = |i: usize| h.add(2 * i).cast::<u16>().read_unaligned() as usize;
    let mut tr = h.add(12);
    let mut rf = tr.add(len(0));
    let mut ct = rf.add(len(1));
    let mut tm = ct.add(len(2));
    let mut vl = tm.add(len(3));
    let mut sl = vl.add(len(4));
    let mut rw = sl.add(len(5));
    let be = |p: &mut *const u8| { let v = u32::from_be(p.cast::<u32>().read_unaligned()); *p = p.add(4); v };
    let mut table = vec![0u32; 3 * 1024];
    let cv = table.as_mut_ptr();
    let mut n = 0usize;
    let mut words = 0u32;
    let mut d = desc;
    for _ in 0..tracks {
        let name = *tr as u32;
        let comps = *tr.add(1) as usize;
        tr = tr.add(2);
        *d = name;
        *d.add(1) = comps as u32;
        for c in 0..comps {
            let mut back = *rf as usize;
            rf = rf.add(1);
            if back == 255 { back = rf.cast::<u16>().read_unaligned() as usize; rf = rf.add(2); }
            if back == 0 {
                let head = *ct as u32;
                ct = ct.add(1);
                let e = cv.add(3 * n);
                *e = words;
                *e.add(1) = head & 127;
                *e.add(2) = head | (name * 4 + c as u32) << 8;
                words += (head & 127) * 4;
                n += 1;
                back = 1;
            }
            let e = cv.add(3 * (n - back));
            *d.add(2 + 2 * c) = *e;
            *d.add(3 + 2 * c) = *e.add(1) * 4;
        }
        d = d.add(10);
    }
    for key in 0..512 {
        for i in 0..n {
            let e = cv.add(3 * i);
            if *e.add(2) >> 8 == key {
                for k in 0..*e.add(1) as usize { *pool.add(*e as usize + 4 * k + 2) = be(&mut vl); }
            }
        }
    }
    let mut previous = pool;
    for i in 0..n {
        let e = cv.add(3 * i);
        let k0 = pool.add(*e as usize);
        let keys = *e.add(1) as usize;
        for k in 0..keys {
            *k0.add(4 * k + 1) = if *e.add(2) & 128 != 0 { *previous.add(4 * k + 1) } else { be(&mut tm) };
        }
        let f = |i: usize| f32::from_bits(*k0.add(i));
        for slot in 1..2 * keys - 1 {
            let k = slot >> 1;
            let out = slot & 1 != 0;
            let byte = *sl;
            sl = sl.add(1);
            let mut z = (byte & 15) as u32;
            if z == 15 {
                let mut shift = 0;
                loop { let x = *rw; rw = rw.add(1); z += ((x & 127) as u32) << shift; if x < 128 { break; } shift += 7; }
            }
            let v = |j: usize| f(4 * j + 2);
            let t = |j: usize| f(4 * j + 1);
            let sel = byte >> 4;
            let predicted = if sel == 1 || sel == 4 {
                if (sel == 1) != out { v(k) - v(k - 1) } else { v(k + 1) - v(k) }
            } else if sel == 2 {
                let (a, b) = if out { (k + 1, k) } else { (k, k - 1) };
                (v(k + 1) - v(k - 1)) / (t(k + 1) - t(k - 1)) * (t(a) - t(b))
            } else if sel == 3 {
                (v(k + 1) - v(k - 1)) * 0.5
            } else if sel == 5 {
                f(4 * k)
            } else if sel == 6 {
                -f(4 * k)
            } else { 0.0 };
            let residual = ((z >> 1) as i32) ^ -((z & 1) as i32);
            *k0.add(4 * k + if out { 3 } else { 0 }) = unord(ord(predicted.to_bits()).wrapping_add(residual));
        }
        previous = k0;
    }
}

/// Initialize before engine/timeline access. Repeated calls are harmless (single thread).
pub fn initialize() {
    unsafe {
        if READY { return; }
        let mut pos = 6;
        let mut timeline_at = 0;
        for id in 0..TABLE_COUNT {
            let mode = at(pos);
            let stride = at(pos + 1) as usize;
            pos += 2;
            let size = uint(&mut pos) as usize;
            let length = uint(&mut pos) as usize;
            let out = vec![0u8; size].leak();
            let p = pos;
            pos += length;
            match mode {
                0 => out.copy_from_slice(core::slice::from_raw_parts(BLOB.as_ptr().add(p), size)),
                1 => {
                    let mut c = p;
                    for i in 0..size / 4 { out.as_mut_ptr().cast::<u32>().add(i).write_unaligned(uint(&mut c).to_le()); }
                }
                2 => {
                    let rows = size / stride;
                    for i in 0..size { *out.as_mut_ptr().add(i) = at(p + (i % stride) * rows + i / stride); }
                }
                _ => if id == CURVE_POOL { timeline_at = p; },
            }
            TABLES[id] = out;
        }
        timeline(timeline_at, TABLES[CURVE_POOL].as_ptr() as *mut u32,
                 TABLES[UNIFORM_DESCRIPTORS].as_ptr() as *mut u32, TABLES[UNIFORM_DESCRIPTORS].len() / 40);
        let size = uint(&mut pos) as usize;
        let raw = |n: usize| alloc::alloc::alloc(core::alloc::Layout::array::<&'static str>(n).unwrap_unchecked()).cast::<&'static str>();
        let fragments = raw(128);
        let mut count = 0;
        let mut start = pos;
        pos += size;
        for i in start..pos {
            if at(i) == 0 {
                *fragments.add(count) = core::str::from_utf8_unchecked(core::slice::from_raw_parts(BLOB.as_ptr().add(start), i + 1 - start));
                count += 1;
                start = i + 1;
            }
        }
        pos += 1;
        let mut all = raw(512);
        for s in 0..PROGRAM_COUNT + 1 {
            let length = uint(&mut pos) as usize;
            for f in 0..length { *all.add(f) = *fragments.add(uint(&mut pos) as usize); }
            SOURCES[s] = core::slice::from_raw_parts(all, length);
            all = all.add(length);
        }
        READY = true;
    }
}

/// Decoded little-endian table bytes (mode 7 tables use the re-laid-out timeline format).
pub fn table(id: usize) -> &'static [u8] { unsafe { TABLES[id] } }

/// NUL-terminated fragments in original glCreateShaderProgramv order.
pub fn sources(index: usize) -> &'static [&'static str] { unsafe { SOURCES[index] } }

pub fn loading_source() -> &'static str { sources(PROGRAM_COUNT)[0] }

pub fn curve_word(index: usize) -> f32 {
    unsafe { f32::from_bits(TABLES[CURVE_POOL].as_ptr().cast::<u32>().add(index).read_unaligned()) }
}
