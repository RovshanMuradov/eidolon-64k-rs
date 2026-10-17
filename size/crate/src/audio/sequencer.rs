//! Native packed trigger-sequencer patterns; pointer lanes adapt to host width.
use super::graph::{Node,State,input,mode};
use super::math::{Stereo as S,random};
use core::ptr;
fn v(x:f64)->S { S::splat(x) }
pub unsafe fn eidolon_sequencer_tick(n:*mut Node,state:*mut State,seed:*mut [i64;2]) {
    let mode=mode(n); let z=S::zero();
    if (*n).last_tick&15==1 && (*n).work[0].is_zero() {
        (*n).work[0]=v(1.0);
        let p=(*n).mode.cast::<u16>().add(1).cast::<u8>();
        *ptr::addr_of_mut!((*n).work[2]).cast::<*const u8>()=p;
        *ptr::addr_of_mut!((*n).work[3]).cast::<*const u8>()=p.add(16);
    }
    let reset=input(n,1).ge(v(0.5)); let mut bpmstep=z;
    let sync=(mode&0xff00)>>8;
    if sync!=0 {
        (*n).work[4]=(*n).work[4]+(*state).bpm/(v(60.0)*v(44100.0)*v(super::arp::FRACTIONS[sync as usize] as f64));
        bpmstep=(*n).work[4].ge(v(1.0));
        (*n).work[4]=reset.select(z,(*n).work[4]-(*n).work[4].floor());
    }
    (*n).work[0]=(*n).work[0]+(input(n,0).ge(v(0.5))|bpmstep).select((*n).work[0],z);
    (*n).work[0]=reset.select(v(1.0),(*n).work[0]);
    let next=(*n).work[0].ge(v(128.0)+v(128.0));
    (*n).work[0]=next.select(v(1.0),(*n).work[0]);
    if !next.is_zero() {
        let maximum=v((mode&255) as f64);
        // Source evaluates s_rand even when the selection chooses the constant lane.
        let rnd=random(&mut *seed).left().abs();
        (*n).work[1]=(*n).work[1]+input(n,3).ge(v(0.5)).select(rnd*maximum,v(1.0));
        (*n).work[1]=(*n).work[1].ge(maximum).select(z,(*n).work[1]);
    }
    (*n).work[1]=input(n,2).ge(v(0.5)).select(z,(*n).work[1]);
    (*n).event=next;
    let pattern=(*n).work[1].ints(); let step=(*n).work[0].ints(); let mut out=[0.0;2];
    for i in 0..2 {
        let p=*ptr::addr_of!((*n).work[2+i]).cast::<*const i8>();
        if (*p.add(pattern[i] as usize) as i32)&step[i]!=0 { out[i]=1.0; }
    }
    (*n).out=S::load(out.as_ptr());
}
