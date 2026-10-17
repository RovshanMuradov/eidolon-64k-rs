//! Synth.cpp delta decoding and ProcessStream ordering, independent of graph dispatch.
use super::alloc::{vec::Vec,boxed::Box};
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Event {
    pub frame: u32,
    pub channel: u8,
    pub kind: u8,
    pub special: u8,
    pub value: u8,
    pub velocity: u8,
}

pub struct Score {
    pub bpm: f32,
    pub frames: u32,
    pub quantum: u32,
    pub events: Vec<Event>,
}

fn word(data: &[u8], at: usize) -> Result<u32, &'static str> {
    Ok(u32::from_le_bytes(data.get(at..at + 4).ok_or("truncated score")?.try_into().unwrap()))
}

fn expand(encoded:&[u8])->Result<Vec<u8>,&'static str> {
    let size=word(encoded,12)? as usize;
    if encoded.get(16+size..)!=Some(&[255u8;4][..]) { return Err("invalid score sentinel"); }
    let mut data=encoded[16..].to_vec();let mut at=0;
    loop {
        let info=word(&data,at)?;at+=4;
        if info==u32::MAX { break; }
        let n=(info&65535) as usize;
        let stride=if info>>24&15==1 {5} else {4};
        let s=data.get_mut(at..at+n*stride).ok_or("truncated event stream")?;
        let mut ticks=0u32;
        for i in 0..n {
            ticks=ticks.wrapping_add(s[i] as u32 | (s[n+i] as u32)<<8);
            // Integer beat-grid prediction is lossless: retain every signed timing residual.
            let stamp=(((ticks as u64*33075+2048)>>12) as u32).wrapping_add_signed(s[2*n+i] as i8 as i32);
            for lane in 0..3 { s[lane*n+i]=(stamp>>(lane*8)) as u8; }
        }
        at+=n*stride;
    }
    if at!=data.len() { return Err("trailing score bytes"); }
    Ok(data)
}

impl Score {
    pub fn decode(encoded: &[u8]) -> Result<Self, &'static str> {
        let bpm = f32::from_bits(word(encoded, 0)?);
        let frames = word(encoded, 4)?;
        let quantum = word(encoded, 8)?;
        if quantum == 0 { return Err("zero event quantum"); }
        let data = expand(encoded)?;
        let mut at = 0;
        let mut events = Vec::new();
        loop {
            let info = word(&data, at)?;
            at += 4;
            if info == u32::MAX { break; }
            let n = (info & 0xffff) as usize;
            let kind = ((info >> 24) & 15) as u8;
            if ![0, 1, 3].contains(&kind) { return Err("unsupported fixed-score stream"); }
            let stride = if kind == 1 { 5 } else { 4 };
            let stream = data.get(at..at + n * stride).ok_or("truncated event stream")?;
            for i in 0..n {
                let stamp = u32::from(stream[i]) | (u32::from(stream[n+i]) << 8) | (u32::from(stream[2*n+i]) << 16);
                events.push(Event {
                    frame: stamp.checked_mul(quantum).ok_or("timestamp overflow")?,
                    channel: (info >> 28) as u8, kind,
                    special: (info >> 16) as u8,
                    value: stream[3*n+i],
                    // Native note-off also reads the adjacent decoded bytes.
                    velocity: if kind != 3 { *data.get(at+4*n+i).ok_or("missing velocity")? } else { 0 },
                });
            }
            at += n * stride;
        }
        if at != data.len() { return Err("trailing score bytes"); }
        // Stable sort preserves stream order for simultaneous events.
        events.sort_by_key(|e| e.frame);
        Ok(Self { bpm, frames, quantum, events })
    }
}

struct Stream { at:usize, count:usize, next:usize, info:u32 }
/// Native stream order; production dispatch advances exactly one 64-frame quantum.
pub struct Scheduler { data:Vec<u8>, streams:[Stream; super::score_code::STREAMS] }
impl Scheduler {
    /// Fixed embedded SCORE (validated at build time by tools/optimize/audio_score): stored
    /// planes regrouped per stream, note-off streams derived from the following note-on
    /// stream's durations, then the same tick expansion as `expand` (floor predictors).
    pub fn fixed() -> Self {
        use super::score_code::{SCORE,STREAMS,DECODED};
        let mut data=super::alloc::vec![0u8;DECODED];
        let mut streams:[Stream;STREAMS]=core::array::from_fn(|_| Stream{at:0,count:0,next:0,info:0});
        unsafe {
            let d=data.as_mut_ptr(); let src=SCORE.as_ptr();
            let mut q=16+4*STREAMS+4;
            for p in 0..5 {
                let mut at=0;
                for (k,stream) in streams.iter_mut().enumerate() {
                    let info=src.add(16+4*k).cast::<u32>().read_unaligned();
                    let n=(info&65535) as usize; let kind=info>>24&15; let stride=if kind==1 {5} else {4};
                    *stream=Stream{at,count:n,next:0,info};
                    if p<stride && (kind!=0 || p==2) { core::ptr::copy_nonoverlapping(src.add(q),d.add(at+p*n),n); q+=n; }
                    at+=stride*n;
                }
            }
            // Note-off streams precede the same channel's note-on stream (asserted by the encoder).
            static mut KEYS:[u32;super::score_code::MAX_NOTES]=[0;super::score_code::MAX_NOTES];
            let keys=core::ptr::addr_of_mut!(KEYS).cast::<u32>();
            for k in 1..STREAMS {
                let (off,on)=(streams.get_unchecked(k-1),streams.get_unchecked(k));
                if on.info>>24&15!=1 || off.info>>24&15!=0 { continue; }
                let (n,s,o)=(on.count,d.add(on.at),d.add(off.at));
                let mut t=0u32;
                for j in 0..n {
                    t+=*s.add(j) as u32 | (*s.add(n+j) as u32)<<8;
                    let value=*s.add(3*n+j) as u32;
                    // key (end tick, note value except on channel 0 | note value); stable sort on key>>8
                    let key=(t+(*src.add(q+j) as u32 | (*src.add(q+n+j) as u32)<<8))<<16
                        |if on.info>>28==0 {0} else {value<<8}|value;
                    let mut i=j;
                    while i>0 && *keys.add(i-1)>>8>key>>8 { *keys.add(i)=*keys.add(i-1); i-=1; }
                    *keys.add(i)=key;
                }
                q+=2*n;
                let mut prev=0u32;
                for i in 0..n {
                    let key=*keys.add(i); let delta=(key>>16)-prev; prev=key>>16;
                    *o.add(i)=delta as u8; *o.add(n+i)=(delta>>8) as u8; *o.add(3*n+i)=key as u8;
                }
            }
            for stream in &streams {
                let (n,s)=(stream.count,d.add(stream.at));
                // Floor predictor; note-off streams (kind 0) are biased 8788/4096 grid units early.
                let kind=stream.info>>24&15;
                let bias=if kind==0 {8788} else {0};
                let mut ticks=0u32; let mut value=0u8;
                for i in 0..n {
                    // Controller values are stored as deltas.
                    if kind==3 { value=value.wrapping_add(*s.add(3*n+i)); *s.add(3*n+i)=value; }
                    ticks=ticks.wrapping_add(*s.add(i) as u32 | (*s.add(n+i) as u32)<<8);
                    let stamp=((ticks*33075-bias)>>12).wrapping_add_signed(*s.add(2*n+i) as i8 as i32);
                    for lane in 0..3 { *s.add(lane*n+i)=(stamp>>(lane*8)) as u8; }
                }
            }
        }
        Self {data,streams}
    }
    pub fn dispatch(&mut self, timestamp: u32, mut emit: impl FnMut(&Event)) {
        let base=self.data.as_ptr();
        for stream in &mut self.streams {
            let n=stream.count;
            while stream.next<n {
                let s=unsafe { base.add(stream.at+stream.next) };
                let b=|i:usize| unsafe { *s.add(i*n) };
                let frame=(b(0) as u32 | (b(1) as u32)<<8 | (b(2) as u32)<<16)*64;
                if frame>timestamp { break; }
                let kind=((stream.info>>24)&15) as u8;
                emit(&Event { frame,channel:(stream.info>>28) as u8,kind,special:(stream.info>>16) as u8,
                    value:b(3),velocity:if kind==3 {0} else {b(4)} });
                stream.next+=1;
            }
        }
    }
}

pub extern "C" fn eidolon_score_new() -> *mut Scheduler {
    Box::into_raw(Box::new(Scheduler::fixed()))
}
pub unsafe extern "C" fn eidolon_score_dispatch(
    state: *mut Scheduler, timestamp: u32,
    emit: extern "C" fn(u32, u32, u32, u32, u32),
) {
    (*state).dispatch(timestamp, |e| emit(e.channel.into(), e.kind.into(), e.special.into(), e.value.into(), e.velocity.into()));
}
pub unsafe extern "C" fn eidolon_score_free(state: *mut Scheduler) { drop(Box::from_raw(state)); }
