//! Native little-endian tables. Pointer offsets and overlapping curve views survive.
include!("generated.rs");

const CURVES: &[u8] = include_bytes!("data/curve_pool.bin");
const RANGES: &[u8] = include_bytes!("data/timeline_ranges.bin");
const TOKENS: &[u8] = include_bytes!("data/timeline_tokens.bin");
const TRACK_RANGES: &[u8] = include_bytes!("data/timeline_track_ranges.bin");
const TRACKS: &[u8] = include_bytes!("data/uniform_descriptors.bin");
const SCENE_PASSES: &[u8] = include_bytes!("data/scene_pass_lists.bin");
const FRAMEBUFFERS: &[u8] = include_bytes!("data/framebuffers.bin");
const PASS_ROUTES: &[u8] = include_bytes!("data/pass_routes.bin");
const PASS_INPUTS: &[u8] = include_bytes!("data/pass_inputs.bin");

pub const ROW_COUNT: usize = 50;
pub const PROGRAM_COUNT: usize = 30;
pub const FRAMEBUFFER_COUNT: usize = 13;
pub const TEXTURE_COUNT: usize = 15;

fn word(bytes: &[u8], index: usize) -> u32 {
    u32::from_le_bytes(bytes[index * 4..index * 4 + 4].try_into().unwrap())
}

pub fn curve_word(index: usize) -> f32 {
    f32::from_bits(word(CURVES, index))
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
    pub fn name(self) -> &'static str {
        UNIFORM_NAMES.iter().find(|(i, _)| *i == self.name_index).unwrap().1
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
        start: f32::from_bits(word(RANGES, index * 2)),
        end: f32::from_bits(word(RANGES, index * 2 + 1)),
        token: word(TOKENS, index) as usize,
        track_offset: word(TRACK_RANGES, index * 2) as usize,
        track_count: word(TRACK_RANGES, index * 2 + 1) as usize,
    }
}

impl Row {
    pub fn tracks(self) -> impl Iterator<Item = Track> {
        (0..self.track_count).map(move |i| {
            let base = self.track_offset + i * 10;
            Track {
                name_index: word(TRACKS, base),
                components: word(TRACKS, base + 1) as usize,
                curves: std::array::from_fn(|c| Curve {
                    offset: word(TRACKS, base + 2 + 2 * c) as usize,
                    words: word(TRACKS, base + 3 + 2 * c) as usize,
                }),
            }
        })
    }

    pub fn passes(self) -> impl Iterator<Item = usize> {
        (0..word(SCENE_PASSES, self.token) as usize)
            .map(move |i| word(SCENE_PASSES, self.token + i + 1) as usize)
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
        attachments: word(FRAMEBUFFERS, base) as usize,
        width: word(FRAMEBUFFERS, base + 1),
        height: word(FRAMEBUFFERS, base + 2),
        divisor: word(FRAMEBUFFERS, base + 3),
        initialization_only: word(FRAMEBUFFERS, base + 4) != 0,
    }
}

impl Framebuffer {
    pub fn dimensions(self, client: [u32; 2]) -> [u32; 2] {
        let [width, height] = if self.width == 0 { client } else { [self.width, self.height] };
        [width / self.divisor, height / self.divisor]
    }
}

#[derive(Clone, Debug)]
pub struct Pass {
    pub program: usize,
    pub framebuffer: Option<usize>,
    pub inputs: Vec<usize>,
}

pub fn pass(index: usize) -> Pass {
    assert!(index < PROGRAM_COUNT);
    let selector = word(PASS_ROUTES, index * 2 + 1) as usize;
    Pass {
        program: word(PASS_ROUTES, index * 2) as usize,
        framebuffer: selector.checked_sub(1),
        inputs: (0..word(PASS_INPUTS, index * 7) as usize)
            .map(|i| word(PASS_INPUTS, index * 7 + i + 1) as usize).collect(),
    }
}
