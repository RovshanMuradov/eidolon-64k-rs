//! VOICEMANAGER lifecycle from SynthNode.cpp, including Rust arpeggiator integration.
use super::graph::{Context, Node, Voice, VoiceWork, input, mode,
    eidolon_create_nodes, eidolon_destroy_voice};
use super::math::{Stereo as S, exp2, lerp};
use core::ptr;
fn v(x: f64) -> S { S::splat(x) }
unsafe fn word(n: *mut Node, i: usize) -> *mut u32 { ptr::addr_of_mut!((*n).work).cast::<u32>().add(i) }
unsafe fn fraction(c: *mut Context, x: S) -> S {
    super::arp::fraction((*c).state,x)
}
unsafe fn set_glide(voice: *mut Voice, note: i32) {
    (*voice).note_value = note;
    (*voice).glide_target = v(note as f64);
    (*voice).glide_base = (*voice).glide_current;
    (*voice).glide_step = S::zero();
}
unsafe fn frequency(note: S) -> S { v(440.0)*exp2((note-v(69.0))*v(0.083333313465118408))/v(44100.0) }

#[inline(never)]
pub unsafe fn eidolon_voice_tick(n: *mut Node, c: *mut Context) {
    let state = (*c).state;
    let mode = mode(n);
    let w = (*n).custom.cast::<VoiceWork>();
    let z = S::zero();
    if (*w).rescan != 0 {
        if (*w).key_count == 0 { (*w).arp_key = -1; }
        (*w).key_count = 0;
        (*w).lowest = 128;
        for note in (0..128).rev() {
            if (*w).keys[note] != 0 {
                if (*w).key_count == 0 { (*w).highest = note as i32; }
                (*w).key_count += 1;
                (*w).lowest = note as i32;
            }
        }
        if (*w).arp_key == -1 { (*n).work[17]=z; (*n).work[18]=z; (*n).work[19]=z; }
        else {
            if (*w).arp_key > (*w).highest { (*w).arp_key=(*w).highest; }
            if (*w).arp_key < (*w).lowest { (*w).arp_key=(*w).lowest; }
        }
        (*w).rescan = 0;
    }
    super::arp::eidolon_arp_step(n,state,mode);
    if (*n).last_tick & 15 == 1 {
        let gi=input(n,2);
        (*n).work[31] = if gi.is_zero() { z } else { gi.ge(v(1.0)).select(v(1.0),fraction(c,gi)) };
        // Native queues consume note-offs and then note-ons in reverse insertion order.
        while *word(n,80) != 0 {
            *word(n,80) -= 1;
            let note = (*word(n,*word(n,80) as usize) & 255) as i32;
            for active in (0..(*w).active_count as usize).rev() {
                let voice=ptr::addr_of_mut!((*w).voices[(*w).active[active] as usize]);
                if note != (*voice).note_value { continue; }
                if voice == (*w).glider {
                    let mut next_key=0;
                    let mut next_time=0;
                    for key in ((*w).lowest..=(*w).highest).rev() {
                        if (*w).keys[key as usize] > next_time { next_key=key; next_time=(*w).keys[key as usize]; }
                    }
                    if next_time != 0 { set_glide(voice,next_key); break; }
                    (*w).glider=ptr::null_mut();
                }
                (*voice).note_value=-1;
                (*voice).gate=z;
                break;
            }
        }
        let slots=64usize >> ((mode & 0x60000000) >> 29);
        while *word(n,81) != 0 {
            *word(n,81) -= 1;
            let data=*word(n,32+*word(n,81) as usize);
            let note=(data & 255) as i32;
            let velocity=data >> 8;
            if !(*w).glider.is_null() { set_glide((*w).glider,note); continue; }
            let mut oldest_time=u32::MAX;
            let mut oldest_off=u32::MAX;
            let mut oldest_slot=None;
            let mut off_slot=None;
            let mut free_slot=None;
            for slot in (0..slots).rev() {
                let voice=ptr::addr_of_mut!((*w).voices[slot]);
                if (*voice).root.is_null() { free_slot=Some(slot); break; }
                if (*voice).note_value < 0 {
                    if (*voice).time < oldest_off { oldest_off=(*voice).time; off_slot=Some(slot); }
                } else if (*voice).time < oldest_time { oldest_time=(*voice).time; oldest_slot=Some(slot); }
            }
            let slot=free_slot.or(off_slot).or(oldest_slot).unwrap();
            let voice=ptr::addr_of_mut!((*w).voices[slot]);
            if free_slot.is_some() { (*w).active[(*w).active_count as usize]=slot as i32; (*w).active_count+=1; }
            else { eidolon_destroy_voice(c,(*voice).root); }
            (*voice).time=(*state).create_tick;
            (*state).create_tick=(*state).create_tick.wrapping_add(1);
            (*voice).note_value=note;
            (*voice).base_note=v(note as f64)/v(128.0);
            (*voice).velocity=v(velocity as f64)/v(128.0);
            // Native computes integer note-69 before conversion for initial frequency.
            (*voice).base_frequency=v(440.0)*exp2(v((note-69) as f64)*v(0.083333313465118408))/v(44100.0);
            (*voice).trigger=v(1.0);
            (*voice).gate=v(1.0);
            let root_offset=*(*state).values.add((*n).offset as usize+1);
            (*voice).root=eidolon_create_nodes(c,root_offset.into(),0);
            if !(*n).work[31].is_zero() {
                (*w).glider=voice;
                (*voice).glide_target=v(note as f64);
                (*voice).glide_base=(*voice).glide_target;
                (*voice).glide_step=z;
            }
        }
        (*n).work[16]=exp2(input(n,1)*v(128.0)*v(0.083333313465118408));
    }
    (*n).out=z;
    for active in (0..(*w).active_count as usize).rev() {
        let voice=ptr::addr_of_mut!((*w).voices[(*w).active[active] as usize]);
        (*state).voice=voice;
        if voice == (*w).glider {
            (*voice).glide_current=lerp((*voice).glide_base,(*voice).glide_target,((*voice).glide_step/(*n).work[31]).min(v(1.0)));
            (*voice).base_note=(*voice).glide_current/v(128.0);
            (*voice).base_frequency=frequency((*voice).glide_current);
            (*voice).glide_step=(*voice).glide_step+v(1.0);
        }
        (*voice).note=(*voice).base_note+input(n,1);
        (*voice).frequency=(*voice).base_frequency*(*n).work[16];
        let root=(*voice).root;
        super::runtime::dispatch(root);
        (*n).out=(*n).out+(*root).out;
        (*voice).trigger=z;
        if (*root).event.is_zero() {
            eidolon_destroy_voice(c,root);
            (*voice).root=ptr::null_mut();
            (*w).active_count-=1;
            if active != (*w).active_count as usize { (*w).active[active]=(*w).active[(*w).active_count as usize]; }
            if voice == (*w).glider { (*w).glider=ptr::null_mut(); }
        }
    }
    (*n).event=if (*w).key_count > 0 { v(1.0) } else { z };
}

/// Synth.cpp AddToNoteController, including channel wakeup and range routing.
pub unsafe fn eidolon_note(c: *mut Context, channel: u32, note: u32, velocity: u32, on: u32) {
    let state=(*c).state;
    let cr=*(*state).globals.add((3+channel*3) as usize);
    (*cr).work[0]=S::zero().eq(S::zero());
    (*cr).work[1]=v(0.125);
    let mut offset=3+16*3;
    for _ in 0..channel { offset+=((*(*state).values.add(offset) >> 8) & 127) as usize+1; }
    let nc=*(*state).globals.add(offset);
    for i in (0..(*nc).num_inputs as usize).rev() {
        let n=(*nc).inputs[i];
        let w=(*n).custom.cast::<VoiceWork>();
        *word(n,23*4)=channel;
        let mode=mode(n);
        if note < (mode & 255) || note > ((mode >> 8) & 255) { continue; }
        (*w).rescan=1;
        if on != 0 {
            (*state).note_tick=(*state).note_tick.wrapping_add(1);
            (*w).keys[note as usize]=(*state).note_tick;
            if mode & 0x000f0000 != 0 {
                if mode & 0x80000000 != 0 { (*w).arp_key=-1; }
            } else { *word(n,32+*word(n,81) as usize)=note | (velocity << 8); *word(n,81)+=1; }
        } else {
            (*w).keys[note as usize]=0;
            if mode & 0x000f0000 == 0 { *word(n,*word(n,80) as usize)=note | (velocity << 8); *word(n,80)+=1; }
        }
        break;
    }
}
