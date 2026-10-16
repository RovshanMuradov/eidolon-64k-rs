//! Standalone fixed-score bootstrap, dispatch, allocation and PCM rendering.
//! Each call owns its graph, bank, RNG and MIDI state; callbacks use a thread-local
//! pointer only while rendering. No source-oracle library or recorded PCM is linked.
use super::{graph::{self,Context,Node,State,Tick},math::Stereo as S};
use std::{alloc::{alloc_zeroed,dealloc,handle_alloc_error,Layout},cell::Cell,collections::BTreeMap,ptr};
#[cfg(target_arch="x86")]
#[allow(deprecated)]
use core::arch::x86::{_mm_getcsr,_mm_setcsr};
#[cfg(target_arch="x86_64")]
#[allow(deprecated)]
use core::arch::x86_64::{_mm_getcsr,_mm_setcsr};

thread_local! { static ACTIVE: Cell<*mut Runtime> = const { Cell::new(ptr::null_mut()) }; }
#[derive(Clone,Copy,Debug,PartialEq,Eq)]
pub struct RenderStats {
    pub frames: u32,
    pub final_tick: u32,
    pub created: u64,
    pub destroyed: u64,
    pub global_hits: u64,
    pub voice_hits: u64,
}
struct Runtime {
    context: Context,
    state: Box<State>,
    patch: Vec<u16>,
    globals: Vec<*mut Node>,
    created_ticks: Vec<u32>,
    ticks: [Option<Tick>;71],
    inits: [Option<Tick>;71],
    seed: [i64;2],
    midi_notes: [i32;256],
    bank: Vec<Vec<[f64;2]>>,
    counts: [u32;512],
    buffers: [*mut [f64;2];512],
    allocations: BTreeMap<usize,Layout>,
    deferred: Vec<*mut u8>,
}
impl Drop for Runtime {
    fn drop(&mut self) {
        for (&p,&layout) in &self.allocations { unsafe { dealloc(p as *mut u8,layout); } }
    }
}
struct ActiveGuard;
impl Drop for ActiveGuard { fn drop(&mut self) { ACTIVE.with(|slot|slot.set(ptr::null_mut())); } }
#[allow(deprecated)]
struct FpGuard(u32);
#[allow(deprecated)]
impl FpGuard {
    unsafe fn new()->Self { let old=_mm_getcsr(); _mm_setcsr(0x1f80); Self(old) }
    unsafe fn synth(&self) { _mm_setcsr(0xffc0); }
}
#[allow(deprecated)]
impl Drop for FpGuard { fn drop(&mut self) { unsafe { _mm_setcsr(self.0); } } }
#[inline]
fn current()->*mut Runtime { ACTIVE.with(Cell::get) }
unsafe extern "C" fn allocate(size:usize)->*mut u8 {
    let layout=Layout::from_size_align(size,16).unwrap();
    let p=alloc_zeroed(layout);
    if p.is_null() { handle_alloc_error(layout); }
    (*current()).allocations.insert(p as usize,layout);
    p
}
unsafe extern "C" fn defer(p:*mut u8) { (*current()).deferred.push(p); }
unsafe fn flush(r:*mut Runtime) {
    while let Some(p)=(*r).deferred.pop() {
        let layout=(*r).allocations.remove(&(p as usize)).expect("duplicate deferred free");
        dealloc(p,layout);
    }
}
unsafe extern "C" fn initialize(n:*mut Node) {
    let r=current(); let c=ptr::addr_of_mut!((*r).context);
    match (*n).id {
        3|36=>super::effects::eidolon_effect_init(n,c,36),
        32|33|51=>super::effects::eidolon_effect_init(n,c,32),
        49=>super::glitch::eidolon_glitch_init(n,c),
        _=>std::process::abort(),
    }
}
unsafe extern "C" fn dispatch(n:*mut Node) {
    let r=current(); let c=ptr::addr_of_mut!((*r).context); let state=(*c).state;
    let seed=ptr::addr_of_mut!((*r).seed);
    match (*n).id {
        0=>super::nodes::eidolon_node_tick(n,state,15),
        21=>super::nodes::eidolon_node_tick(n,state,2),
        65..=70=>super::nodes::eidolon_node_tick(n,state,65),
        3=>super::voice::eidolon_voice_tick(n,c),
        6|7=>super::oscillator::eidolon_oscillator_tick(n,state,seed,(*n).id),
        8|35=>super::sources::eidolon_random_tick(n,state,seed,(*n).id),
        9|32|33|36|38|43|51=>super::effects::eidolon_effect_tick(n,state,(*n).id),
        40=>super::sequencer::eidolon_sequencer_tick(n,state,seed),
        42=>super::sources::eidolon_sampler_tick(n,state),
        49=>super::glitch::eidolon_glitch_tick(n,state,seed),
        52=>super::sources::eidolon_bank_tick(n,state,(*r).counts.as_ptr(),(*r).buffers.as_ptr()),
        57=>super::effects::eidolon_formant_tick(n,c),
        id=>super::nodes::eidolon_node_tick(n,state,id),
    }
}
unsafe fn midi(r:*mut Runtime,channel:u32,mut value:i32,cc:u32) {
    if cc==0 { value-=128; }
    if cc>=112 {
        let note=cc-112;
        let slot=(channel*16+note) as usize;
        let c=ptr::addr_of_mut!((*r).context);
        if (*r).midi_notes[slot]!=0 { super::voice::eidolon_note(c,channel,60+note,value as u32,0); }
        if value!=0 { super::voice::eidolon_note(c,channel,60+note,value as u32,1); }
        (*r).midi_notes[slot]=value;
    }
    (*(*r).context.state).midi[(channel*128+cc) as usize]=S::splat(value as f64)/S::splat(128.0);
}

/// CPU diagnostic prefix entrypoint. Production calls the exact-size `audio::render`.
pub fn render_prefix(output:&mut [f32])->Result<RenderStats,&'static str> {
    if output.is_empty() || output.len()%128!=0 || output.len()>super::TOTAL_FRAMES as usize*2 {
        return Err("audio prefix must contain 64-frame quanta within the fixed score");
    }
    if !std::is_x86_feature_detected!("sse4.1") { return Err("audio requires SSE4.1"); }
    if !current().is_null() { return Err("audio renderer cannot be reentered on the same thread"); }
    let mut scheduler=super::score::Scheduler::fixed()?;
    unsafe {
        let fp=FpGuard::new();
        let state_ptr=alloc_zeroed(Layout::new::<State>()).cast::<State>();
        if state_ptr.is_null() { handle_alloc_error(Layout::new::<State>()); }
        let state=Box::from_raw(state_ptr);
        let mut runtime=Box::new(Runtime {
            context:Context {state:state_ptr,ticks:ptr::null(),inits:ptr::null(),alloc:allocate,free:defer,created:0,destroyed:0,global_hits:0,voice_hits:0},
            state,patch:super::data::PATCH.chunks_exact(2).map(|b|u16::from_le_bytes([b[0],b[1]])).collect(),
            globals:vec![ptr::null_mut();3836],created_ticks:vec![0;3836],ticks:[Some(dispatch);71],inits:[None;71],
            seed:[1,31337],midi_notes:[0;256],bank:Vec::new(),counts:[0;512],buffers:[ptr::null_mut();512],
            allocations:BTreeMap::new(),deferred:Vec::new(),
        });
        for id in [3,32,33,36,49,51] { runtime.inits[id]=Some(initialize); }
        runtime.context.ticks=runtime.ticks.as_ptr(); runtime.context.inits=runtime.inits.as_ptr();
        runtime.state.tick=1; runtime.state.values=runtime.patch.as_ptr();
        runtime.state.globals=runtime.globals.as_mut_ptr(); runtime.state.created_ticks=runtime.created_ticks.as_mut_ptr();
        runtime.state.constant_offset=3328; runtime.state.max_offset=3836;
        let r=ptr::from_mut(runtime.as_mut());
        ACTIVE.with(|slot|slot.set(r)); let active=ActiveGuard;
        let c=ptr::addr_of_mut!((*r).context);
        for offset in (3328..3728).step_by(2) { graph::eidolon_create_node(c,64,1,offset,1); }
        for offset in (3728..3836).step_by(4) { graph::eidolon_create_node(c,64,2,offset,1); }
        let root=graph::eidolon_create_nodes(c,0,1);
        for &(id,_) in super::data::WAVES {
            let mut wave=super::data::wave(id).unwrap();
            (*r).counts[id as usize]=wave.len() as u32; (*r).buffers[id as usize]=wave.as_mut_ptr();
            (*r).bank.push(wave);
        }
        fp.synth();
        (*state_ptr).bpm=S::splat(scheduler.score.bpm as f64);
        let frames=(output.len()/2) as u32;
        for frame in (0..frames).step_by(64) {
            scheduler.dispatch(frame,|event| {
                if event.kind==3 { midi(r,event.channel.into(),event.value.into(),event.special.into()); }
                else { super::voice::eidolon_note(c,event.channel.into(),event.value.into(),event.velocity.into(),u32::from(event.kind==1)); }
            });
            for at in frame..frame+64 {
                dispatch(root);
                let stereo=(*root).out.pcm();
                output[at as usize*2]=stereo[0]; output[at as usize*2+1]=stereo[1];
                (*state_ptr).tick+=1;
            }
            flush(r);
        }
        let stats=RenderStats {frames,final_tick:(*state_ptr).tick,created:(*c).created,destroyed:(*c).destroyed,global_hits:(*c).global_hits,voice_hits:(*c).voice_hits};
        drop(active); drop(runtime); drop(fp);
        Ok(stats)
    }
}
