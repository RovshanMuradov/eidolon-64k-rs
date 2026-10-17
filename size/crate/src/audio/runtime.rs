//! Standalone fixed-score bootstrap, dispatch, allocation and PCM rendering.
//! Each call owns its graph, bank, RNG and MIDI state through explicit context pointers.
use super::{graph::{self,Context,Node,State},math::Stereo as S};
use super::alloc::{alloc::{alloc_zeroed,dealloc,handle_alloc_error,Layout},boxed::Box};
use core::ptr;
#[cfg(target_arch="x86")]
#[allow(deprecated)]
use core::arch::x86::{_mm_getcsr,_mm_setcsr};
#[cfg(target_arch="x86_64")]
#[allow(deprecated)]
use core::arch::x86_64::{_mm_getcsr,_mm_setcsr};

#[derive(Clone,Copy,Debug,PartialEq,Eq)]
pub struct RenderStats {
    pub frames: u32,
    pub final_tick: u32,
    pub created: u64,
    pub destroyed: u64,
    pub global_hits: u64,
    pub voice_hits: u64,
}
#[repr(C)]
struct Runtime {
    context: Context,
    state: State,
    globals: [*mut Node;3836],
    created_ticks: [u32;3836],
    seed: [i64;2],
    midi_notes: [i32;256],
    counts: [u32;512],
    buffers: [*mut [f64;2];512],
    allocations: *mut Allocation,
    deferred: *mut Allocation,
}
#[repr(C,align(16))]
struct Allocation { prev:*mut Allocation, next:*mut Allocation, deferred:*mut Allocation, size:usize }
impl Drop for Runtime {
    fn drop(&mut self) {
        unsafe { while !self.allocations.is_null() { release(self,self.allocations); } }
    }
}
#[allow(deprecated)]
struct FpGuard(u32);
#[allow(deprecated)]
impl FpGuard {
    unsafe fn new()->Self { let old=_mm_getcsr(); _mm_setcsr(0x1f80); Self(old) }
    unsafe fn synth(&self) { _mm_setcsr(0xffc0); }
}
#[allow(deprecated)]
impl Drop for FpGuard { fn drop(&mut self) { unsafe { _mm_setcsr(self.0); } } }
pub(super) unsafe fn allocate(c:*mut Context,size:usize)->*mut u8 {
    let r=c.cast::<Runtime>();
    let size=size+core::mem::size_of::<Allocation>();
    let layout=Layout::from_size_align_unchecked(size,16);
    let p=alloc_zeroed(layout).cast::<Allocation>();
    if p.is_null() { handle_alloc_error(layout); }
    (*p).size=size; (*p).next=(*r).allocations;
    if !(*p).next.is_null() { (*(*p).next).prev=p; }
    (*r).allocations=p;
    p.add(1).cast()
}
pub(super) unsafe fn defer(c:*mut Context,p:*mut u8) {
    let r=c.cast::<Runtime>(); let p=p.cast::<Allocation>().sub(1);
    (*p).deferred=(*r).deferred; (*r).deferred=p;
}
unsafe fn release(r:*mut Runtime,p:*mut Allocation) {
    if (*p).prev.is_null() { (*r).allocations=(*p).next; }
    else { (*(*p).prev).next=(*p).next; }
    if !(*p).next.is_null() { (*(*p).next).prev=(*p).prev; }
    dealloc(p.cast(),Layout::from_size_align_unchecked((*p).size,16));
}
unsafe fn flush(r:*mut Runtime) {
    while !(*r).deferred.is_null() {
        let p=(*r).deferred; (*r).deferred=(*p).deferred; release(r,p);
    }
}
pub(super) unsafe fn initialize(n:*mut Node) {
    let c=(*n).context;
    match (*n).id {
        3|36=>super::effects::eidolon_effect_init(n,c,36),
        32|33|51=>super::effects::eidolon_effect_init(n,c,32),
        49=>super::glitch::eidolon_glitch_init(n,c),
        _=>{},
    }
}
pub(super) unsafe fn dispatch(n:*mut Node) {
    let id=(*n).id;
    if id==64 {return;}
    let c=(*n).context; let r=c.cast::<Runtime>(); let state=(*c).state;
    let seed=ptr::addr_of_mut!((*r).seed);
    // Stateless nodes and CHANNELROOT's independently updated envelope bypass caching.
    if !matches!(id,1|29|35|65..=70) && graph::cached(n,state) {return;}
    // Centralized fixed-patch traversal. Variable/reversed/conditional traversals stay local.
    const COUNTS:[u8;71]=[
        2,0,0,4,3,5,4,6,2,4,2,2,0,2,0,2,2,2,2,2,3,0,1,3,0,2,0,1,0,0,3,0,
        2,5,2,0,6,0,6,1,4,0,7,3,0,1,0,2,2,6,0,2,0,0,0,0,0,2,0,0,0,0,0,0,0,0,0,0,0,0,0];
    for i in usize::from(id==3)..*COUNTS.get_unchecked(id as usize) as usize {graph::call_input(n,i);}
    match id {
        0=>super::nodes::eidolon_node_tick(n,state,15),
        21=>super::nodes::eidolon_node_tick(n,state,2),
        65..=70=>super::nodes::eidolon_node_tick(n,state,65),
        3=>super::voice::eidolon_voice_tick(n,c),
        6|7=>super::oscillator::eidolon_oscillator_tick(n,state,seed,(*n).id),
        8|35=>super::sources::eidolon_random_tick(n,state,seed,(*n).id),
        9=>super::effects::biquad(n,state),
        32|33|51=>super::effects::delay(n,state,id),
        36=>super::effects::reverb(n),
        38=>super::effects::compressor(n),
        43=>super::effects::state_variable(n,state),
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

/// PATCH words from the isomorphic record streams of patch_code (tools/optimize/audio_patch).
fn patch()->super::alloc::vec::Vec<u16> {
    use super::patch_code::*;
    let mut out=super::alloc::vec![0u16;WORDS];
    let mut starts=super::alloc::vec![0u16;RECORDS];
    let c=|k:usize| (if k<200 { 3328+2*k } else { 3728+4*(k-200) }) as u16;
    unsafe {
        let code=CODE.as_ptr().cast::<u16>();
        let (o,s)=(out.as_mut_ptr(),starts.as_mut_ptr());
        let mut at=0usize;
        for r in 0..RECORDS { *s.add(r)=at as u16; let info=code.add(r).read_unaligned() as usize; at+=1+((info>>8)&127)+MODE_WORDS[info&127] as usize; }
        let (mut refs,mut modes)=(code.add(RECORDS),code.add(RECORDS+REFS));
        let (mut nn,mut nm,mut ns)=(PINNED,0,200);
        let mut p=o;
        for r in 0..RECORDS {
            let info=code.add(r).read_unaligned();
            *p=info; p=p.add(1);
            for _ in 0..(info>>8)&127 {
                let x=refs.read_unaligned() as usize; refs=refs.add(1);
                *p=if x==0 { nn+=1; *s.add(nn-1) }
                    else if x<=RECORDS { *s.add(x-1) }
                    else if x==RECORDS+1 { nm+=1; c(nm-1) }
                    else if x==RECORDS+2 { ns+=1; c(ns-1) }
                    else { c(x-RECORDS-3) };
                p=p.add(1);
            }
            for _ in 0..MODE_WORDS[(info&127) as usize] { *p=modes.read_unaligned(); modes=modes.add(1); p=p.add(1); }
        }
        core::ptr::copy_nonoverlapping(modes.cast::<u8>(),p.cast::<u8>(),2*(WORDS-at));
    }
    out
}

/// CPU diagnostic prefix entrypoint. Production calls the exact-size `audio::render`.
pub fn render_prefix(output:&mut [f32])->Result<RenderStats,&'static str> {
    #[cfg(not(feature="sizecoded"))]
    if output.is_empty() || output.len()%128!=0 || output.len()>super::TOTAL_FRAMES as usize*2 {
        return Err("prefix");
    }
    #[cfg(target_arch="x86")]
    let features=core::arch::x86::__cpuid(1).ecx;
    #[cfg(target_arch="x86_64")]
    let features=core::arch::x86_64::__cpuid(1).ecx;
    if features&(1<<19)==0 { return Err("sse4.1"); }
    let mut scheduler=super::score::Scheduler::fixed();
    unsafe {
        let fp=FpGuard::new();
        // Initialize the owning context before constructing graph nodes.
        let r=alloc_zeroed(Layout::new::<Runtime>()).cast::<Runtime>();
        if r.is_null() { handle_alloc_error(Layout::new::<Runtime>()); }
        let state_ptr=ptr::addr_of_mut!((*r).state);
        ptr::addr_of_mut!((*r).context).write(Context {state:state_ptr,created:0,destroyed:0,global_hits:0,voice_hits:0});
        let mut runtime=Box::from_raw(r);
        runtime.seed=[1,31337];
        let patch=patch();
        runtime.state.tick=1; runtime.state.values=patch.as_ptr();
        runtime.state.globals=runtime.globals.as_mut_ptr(); runtime.state.created_ticks=runtime.created_ticks.as_mut_ptr();
        runtime.state.constant_offset=3328; runtime.state.max_offset=3836;
        let r=ptr::from_mut(runtime.as_mut());
        let c=ptr::addr_of_mut!((*r).context);
        let mut offset=3328;
        while offset<3728 { graph::eidolon_create_node(c,64,1,offset,1); offset+=2; }
        while offset<3836 { graph::eidolon_create_node(c,64,2,offset,1); offset+=4; }
        let root=graph::eidolon_create_nodes(c,0,1);
        let mut bank=super::bank::load()?;
        for (i,&id) in super::data::WAVE_IDS.iter().enumerate() {
            (*r).counts[id as usize]=bank.starts[i+1]-bank.starts[i];
            (*r).buffers[id as usize]=bank.samples.as_mut_ptr().add(bank.starts[i] as usize);
        }
        fp.synth();
        (*state_ptr).bpm=S::splat(80.0);
        let frames=(output.len()/2) as u32;
        let o=output.as_mut_ptr();
        let mut frame=0;
        while frame<frames {
            scheduler.dispatch(frame,|event| {
                if event.kind==3 { midi(r,event.channel.into(),event.value.into(),event.special.into()); }
                else { super::voice::eidolon_note(c,event.channel.into(),event.value.into(),event.velocity.into(),u32::from(event.kind==1)); }
            });
            for at in frame..frame+64 {
                dispatch(root);
                let stereo=(*root).out.pcm();
                *o.add(at as usize*2)=stereo[0]; *o.add(at as usize*2+1)=stereo[1];
                (*state_ptr).tick+=1;
            }
            flush(r);
            frame+=64;
        }
        let stats=RenderStats {frames,final_tick:(*state_ptr).tick,created:(*c).created,destroyed:(*c).destroyed,global_hits:(*c).global_hits,voice_hits:(*c).voice_hits};
        drop(runtime); drop(fp);
        Ok(stats)
    }
}
