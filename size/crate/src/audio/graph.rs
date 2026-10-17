//! Pinned SynthNode.cpp graph allocation/cache and recursive voice destruction.
//! Pointer-bearing records have host pointer width and an explicit owning context.
use super::math::Stereo;
use core::ptr;

#[repr(C)]
pub struct Node {
    pub out: Stereo,
    pub last_tick: u32,
    pub custom: *mut u8,
    pub mode: *const u32,
    pub num_inputs: u32,
    pub global: u32,
    pub offset: u32,
    pub event: Stereo,
    pub work: [Stereo; 32],
    pub inputs: [*mut Node; 16],
    pub id: u32,
    pub special: *mut u8,
    pub context: *mut Context,
}
#[repr(C)]
pub struct Voice {
    pub root: *mut Node,
    pub note_value: i32,
    pub time: u32,
    #[cfg(target_pointer_width = "32")]
    pub padding: i32,
    pub base_frequency: Stereo,
    pub base_note: Stereo,
    pub frequency: Stereo,
    pub note: Stereo,
    pub velocity: Stereo,
    pub trigger: Stereo,
    pub gate: Stereo,
    pub aftertouch: Stereo,
    pub glide_base: Stereo,
    pub glide_target: Stereo,
    pub glide_current: Stereo,
    pub glide_step: Stereo,
    pub tail_padding: [Stereo; 3],
}
#[repr(C)]
pub struct VoiceWork {
    pub active_count: i32,
    pub glider: *mut Voice,
    pub padding: [i32; 2],
    pub rescan: i32,
    pub key_count: i32,
    pub lowest: i32,
    pub highest: i32,
    pub arp_key: i32,
    pub arp_octave: i32,
    pub arp_loop: i32,
    pub arp_sequence: *const u16,
    pub padding3: [u32; 52],
    pub keys: [u32; 128],
    pub active: [i32; 128],
    pub voices: [Voice; 128],
}
#[repr(C)]
pub struct State {
    pub tick: u32,
    pub values: *const u16,
    pub created_ticks: *mut u32,
    pub globals: *mut *mut Node,
    pub create_tick: u32,
    pub voice: *mut Voice,
    pub constant_offset: u32,
    pub max_offset: u32,
    pub bpm: Stereo,
    pub midi: [Stereo; 2048],
    pub aftertouch: [Stereo; 2048],
    pub waves: [*mut Stereo; 32],
    pub song: *mut u8,
    pub note_tick: u32,
}
#[repr(C)]
pub struct Context {
    pub state: *mut State,
    pub created: u64,
    pub destroyed: u64,
    pub global_hits: u64,
    pub voice_hits: u64,
}

/// RenderStats node counters are CPU diagnostics only; the sizecoded Windows runtime skips them.
pub const DIAGNOSTIC_COUNTS: bool = !cfg!(all(feature = "sizecoded", target_os = "windows"));

pub unsafe fn eidolon_create_node(c: *mut Context, id: u32, refs: u32, offset: u32, global: u32) -> *mut Node {
    let s = (*c).state;
    let n = super::runtime::allocate(c, core::mem::size_of::<Node>()).cast::<Node>();
    (*n).context = c;
    if id == 64 {
        let p = (*s).values.add(offset as usize);
        let left = f32::from_bits(ptr::read_unaligned(p.cast::<u32>())) as f64;
        let right = if refs == 2 { f32::from_bits(ptr::read_unaligned(p.add(2).cast::<u32>())) as f64 } else { left };
        (*n).out = Stereo::load([left, right].as_ptr());
    }
    *(*s).globals.add(offset as usize) = n;
    (*n).global = global;
    (*n).offset = offset;
    (*n).num_inputs = refs;
    (*n).id = id;
    if DIAGNOSTIC_COUNTS { (*c).created += 1; }
    super::runtime::initialize(n);
    n
}

pub unsafe fn eidolon_create_nodes(c: *mut Context, offset: u32, global: u32) -> *mut Node {
    let s = (*c).state;
    let cached = *(*s).globals.add(offset as usize);
    if global != 0 {
        if !cached.is_null() { if DIAGNOSTIC_COUNTS { (*c).global_hits += 1; } return cached; }
    } else {
        let created = (*s).created_ticks.add(offset as usize);
        if offset >= (*s).constant_offset || *created == (*s).create_tick {
            if DIAGNOSTIC_COUNTS { (*c).voice_hits += 1; }
            return eidolon_create_nodes(c, offset, 1);
        }
        *created = (*s).create_tick;
    }
    let values = (*s).values.add(offset as usize);
    let info = *values as u32;
    if ((info & 0x8000) != 0) == (global != 0) {
        let refs = (info >> 8) & 127;
        let n = eidolon_create_node(c, info & 127, refs, offset, global);
        for i in 0..refs as usize {
            (*n).inputs[i] = eidolon_create_nodes(c, *values.add(i + 1) as u32, global);
        }
        (*n).mode = values.add(refs as usize + 1).cast();
    } else if global != 0 { return ptr::null_mut(); }
    eidolon_create_nodes(c, offset, 1)
}

pub unsafe fn eidolon_destroy_voice(c: *mut Context, n: *mut Node) {
    if n.is_null() || (*n).global != 0 { return; }
    (*n).global = 1; // mark before walking cycles/shared inputs
    if !(*n).custom.is_null() { super::runtime::defer(c, (*n).custom); }
    let mut i = 0;
    loop {
        let remaining = (*n).num_inputs;
        (*n).num_inputs = remaining.wrapping_sub(1);
        if remaining == 0 { break; }
        eidolon_destroy_voice(c, (*n).inputs[i]);
        i += 1;
    }
    if DIAGNOSTIC_COUNTS { (*c).destroyed += 1; }
    super::runtime::defer(c, n.cast()); // deferred allocator keeps marked nodes alive during traversal
}

#[inline]
pub unsafe fn call_input(n: *mut Node, i: usize) {
    let p = (*n).inputs[i];
    super::runtime::dispatch(p);
}
#[inline]
pub unsafe fn input(n: *mut Node, i: usize) -> Stereo { (*(*n).inputs[i]).out }
#[inline]
pub unsafe fn cached(n: *mut Node, s: *mut State) -> bool {
    if (*n).last_tick == (*s).tick { return true; }
    (*n).last_tick = (*s).tick;
    false
}
#[inline]
pub unsafe fn mode(n: *mut Node) -> u32 { ptr::read_unaligned((*n).mode) }

/// ABI fingerprint used by the independently compiled source adapter before rendering.
pub unsafe extern "C" fn eidolon_layout(out: *mut usize) {
    use core::mem::{size_of, offset_of};
    let values = [size_of::<Node>(), size_of::<Voice>(), size_of::<VoiceWork>(), size_of::<State>(),
        offset_of!(Node, event), offset_of!(Node, work), offset_of!(Node, inputs), offset_of!(Node, id),
        offset_of!(VoiceWork, keys), offset_of!(VoiceWork, active), offset_of!(VoiceWork, voices),
        offset_of!(State, bpm), offset_of!(State, voice), offset_of!(State, note_tick)];
    ptr::copy_nonoverlapping(values.as_ptr(), out, values.len());
}
