//! Native arpeggiator sequencing and exact float32 BPM-fraction table.
use super::graph::{Node, State, VoiceWork, input};
use super::math::Stereo as S;
use core::ptr;
fn v(x:f64)->S { S::splat(x) }
unsafe fn word(n:*mut Node,i:usize)->*mut u32 { ptr::addr_of_mut!((*n).work).cast::<u32>().add(i) }
pub const FRACTIONS: [f32;33] = [
    4.0/128.0,4.0/64.0*(2.0/3.0),4.0/128.0*1.5,
    4.0/64.0,4.0/32.0*(2.0/3.0),4.0/64.0*1.5,
    4.0/32.0,4.0/16.0*(2.0/3.0),4.0/32.0*1.5,
    4.0/16.0,4.0/8.0*(2.0/3.0),4.0/16.0*1.5,
    4.0/8.0,4.0/4.0*(2.0/3.0),4.0/8.0*1.5,
    4.0/4.0,4.0/2.0*(2.0/3.0),4.0/4.0*1.5,
    4.0/2.0,4.0*(2.0/3.0),4.0/2.0*1.5,
    4.0,6.0,1.5,2.5,3.5,4.5,5.5,6.5,7.5,3.0,5.0,7.0,
];
pub unsafe fn fraction(state:*mut State,value:S)->S {
    let ix=(value.clamp(v(1.0),S::zero())*v(32.0)).ints();
    S::load([FRACTIONS[ix[0] as usize] as f64,FRACTIONS[ix[1] as usize] as f64].as_ptr())*v(60.0)*v(44100.0)/(*state).bpm
}
pub unsafe extern "C" fn eidolon_fraction(state:*mut State,value:*const S,out:*mut S) { *out=fraction(state,*value); }

unsafe fn clear(w:*mut VoiceWork) {
    for i in (0..(*w).active_count as usize).rev() {
        let voice=ptr::addr_of_mut!((*w).voices[(*w).active[i] as usize]);
        if (*w).key_count == 0 || voice != (*w).glider {
            (*voice).gate=S::zero(); (*voice).note_value=-1;
            if voice == (*w).glider { (*w).glider=ptr::null_mut(); }
        }
    }
}
unsafe fn insert(n:*mut Node,w:*mut VoiceWork,mode:u32,transpose:i32,velocity:u32) {
    let run=(mode>>16)&15;
    let octaves=((mode>>20)&15) as i32;
    if run == 0 { return; }
    // All fixed-patch arpeggiators use ascending run1; compact_embed.py verifies it.
    let first=(*w).lowest;
    let last=(*w).highest;
    if (*w).arp_key == -1 { (*w).arp_octave=0; (*w).arp_key=first; }
    else if (*w).arp_key == last {
        (*w).arp_key=first; (*w).arp_octave+=1;
        if (*w).arp_octave >= octaves { (*w).arp_octave=0; }
    } else {
        while (*w).arp_key != last {
            (*w).arp_key+=1;
            if (*w).keys[(*w).arp_key as usize] != 0 { break; }
        }
    }
    *word(n,32+*word(n,81) as usize)=((*w).arp_key+12*(*w).arp_octave+transpose) as u32 | (velocity<<8);
    *word(n,81)+=1;
}
pub unsafe fn eidolon_arp_step(n:*mut Node,state:*mut State,mode:u32) {
    if mode & 0x000f0000 == 0 { return; }
    let w=(*n).custom.cast::<VoiceWork>();
    if (*w).arp_sequence.is_null() {
        let p=(*state).values.add(((*state).max_offset+1+((mode&0x1f000000)>>24)*33) as usize);
        (*w).arp_loop=*p as i32; (*w).arp_sequence=p.add(1);
    }
    if (*w).key_count == 0 { clear(w); return; }
    let step=fraction(state,input(n,3));
    let mut velocity=0;
    let mut transpose=0;
    (*n).work[17]=(*n).work[17]-v(1.0);
    if !(*n).work[17].lt(S::zero()).is_zero() {
        let value=*(*w).arp_sequence.add(*word(n,19*4) as usize) as u32;
        velocity=value>>8;
        let note=value&255;
        let gate=note>>6;
        transpose=(note&63) as i32-32;
        if velocity != 0 || note != 0 { (*n).work[18]=step/v([3.0,2.0,1.5,1.0][gate as usize]); }
        (*n).work[17]=step;
        *word(n,19*4)+=1;
        if *word(n,19*4)>=32 { *word(n,19*4)=(*w).arp_loop as u32; }
    }
    let gateoff=(*n).work[18].lt(S::zero());
    if velocity != 0 || !gateoff.is_zero() {
        (*n).work[18]=gateoff.select(v(418381.75),(*n).work[18]); clear(w);
    }
    if velocity != 0 { insert(n,w,mode,transpose,velocity); }
    (*n).work[18]=(*n).work[18]-v(1.0);
}
