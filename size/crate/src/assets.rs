//! Native little-endian tables. Pointer offsets and overlapping curve views survive.
include!("generated.rs");

use alloc::vec::Vec;
macro_rules! native_table {
    ($name:ident, $file:literal, $id:literal) => {
        #[allow(non_snake_case)]
        fn $name() -> &'static [u8] {
            #[cfg(feature = "compact-graphics")]
            { crate::compact_graphics::table($id) }
            #[cfg(not(feature = "compact-graphics"))]
            { include_bytes!($file) }
        }
    };
}
native_table!(CURVES, "data/curve_pool.bin", 0);
native_table!(RANGES, "data/timeline_ranges.bin", 8);
native_table!(TOKENS, "data/timeline_tokens.bin", 9);
native_table!(TRACK_RANGES, "data/timeline_track_ranges.bin", 10);
native_table!(TRACKS, "data/uniform_descriptors.bin", 11);
native_table!(SCENE_PASSES, "data/scene_pass_lists.bin", 7);
native_table!(FRAMEBUFFERS, "data/framebuffers.bin", 1);
native_table!(PASS_ROUTES, "data/pass_routes.bin", 3);
native_table!(PASS_INPUTS, "data/pass_inputs.bin", 2);

pub fn initialize() {
    #[cfg(feature = "compact-graphics")]
    crate::compact_graphics::initialize();
}
pub fn sources(index: usize) -> &'static [&'static str] {
    #[cfg(feature = "compact-graphics")]
    { crate::compact_graphics::sources(index) }
    #[cfg(not(feature = "compact-graphics"))]
    { PROGRAM_SOURCES[index] }
}
pub fn loading_source() -> &'static str {
    #[cfg(feature = "compact-graphics")]
    { crate::compact_graphics::loading_source() }
    #[cfg(not(feature = "compact-graphics"))]
    { LOADING_SOURCE }
}

pub const ROW_COUNT: usize = 50;
pub const PROGRAM_COUNT: usize = 30;
pub const FRAMEBUFFER_COUNT: usize = 13;
pub const TEXTURE_COUNT: usize = 15;

fn word(bytes: &[u8], index: usize) -> u32 {
    // Fixed embedded tables; every index is proven by the exact host/GPU regressions.
    debug_assert!(index < bytes.len() / 4);
    u32::from_le(unsafe { bytes.as_ptr().cast::<u32>().add(index).read_unaligned() })
}

pub fn curve_word(index: usize) -> f32 {
    f32::from_bits(word(CURVES(), index))
}

#[derive(Clone, Copy, Debug)]
pub struct Curve {
    pub offset: usize,
    pub words: usize,
}

#[derive(Clone, Copy, Debug)]
pub struct Track {
    pub name_index: u32,
    pub components: usize,
    pub curves: [Curve; 4],
}

impl Track {
    /// NUL-terminated uniform name (the terminator is part of the slice).
    pub fn name(self) -> &'static str {
        let mut p = crate::gl_names::UNIFORMS.as_ptr();
        unsafe { while (*p).0 != self.name_index { p = p.add(1); } (*p).1 }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Row {
    pub index: usize,
    pub start: f32,
    pub end: f32,
    pub token: usize,
    track_offset: usize,
    pub track_count: usize,
}

pub fn row(index: usize) -> Row {
    assert!(index < ROW_COUNT);
    Row {
        index,
        start: f32::from_bits(word(RANGES(), index * 2)),
        end: f32::from_bits(word(RANGES(), index * 2 + 1)),
        token: word(TOKENS(), index) as usize,
        track_offset: word(TRACK_RANGES(), index * 2) as usize,
        track_count: word(TRACK_RANGES(), index * 2 + 1) as usize,
    }
}

impl Row {
    pub fn tracks(self) -> impl Iterator<Item = Track> {
        (0..self.track_count).map(move |i| {
            let base = self.track_offset + i * 10;
            Track {
                name_index: word(TRACKS(), base),
                components: word(TRACKS(), base + 1) as usize,
                curves: core::array::from_fn(|c| Curve {
                    offset: word(TRACKS(), base + 2 + 2 * c) as usize,
                    words: word(TRACKS(), base + 3 + 2 * c) as usize,
                }),
            }
        })
    }

    pub fn passes(self) -> impl Iterator<Item = usize> {
        (0..word(SCENE_PASSES(), self.token) as usize)
            .map(move |i| word(SCENE_PASSES(), self.token + i + 1) as usize)
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Framebuffer {
    pub attachments: usize,
    pub width: u32,
    pub height: u32,
    pub divisor: u32,
    pub initialization_only: bool,
}

pub fn framebuffer(index: usize) -> Framebuffer {
    assert!(index < FRAMEBUFFER_COUNT);
    let base = index * 5;
    Framebuffer {
        attachments: word(FRAMEBUFFERS(), base) as usize,
        width: word(FRAMEBUFFERS(), base + 1),
        height: word(FRAMEBUFFERS(), base + 2),
        divisor: word(FRAMEBUFFERS(), base + 3),
        initialization_only: word(FRAMEBUFFERS(), base + 4) != 0,
    }
}

impl Framebuffer {
    pub fn dimensions(self, client: [u32; 2]) -> [u32; 2] {
        let [width, height] = if self.width == 0 { client } else { [self.width, self.height] };
        [width / self.divisor, height / self.divisor]
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Pass {
    pub program: usize,
    pub framebuffer: Option<usize>,
    input_base: usize,
    pub input_count: usize,
}

impl Pass {
    /// Texture index bound to sampler input `i < input_count`.
    pub fn input(self, i: usize) -> usize { word(PASS_INPUTS(), self.input_base + i + 1) as usize }
}

pub fn pass(index: usize) -> Pass {
    debug_assert!(index < PROGRAM_COUNT);
    let selector = word(PASS_ROUTES(), index * 2 + 1) as usize;
    Pass {
        program: word(PASS_ROUTES(), index * 2) as usize,
        framebuffer: selector.checked_sub(1),
        input_base: index * 7,
        input_count: word(PASS_INPUTS(), index * 7) as usize,
    }
}
