//! Pinned LFO/OSCILLATOR phase, unison, waveform and RNG operation order.
use super::graph::{Node,State,input,mode};
use super::math::{Stereo as S,exp2,sin,random,lerp};
fn v(x:f64)->S { S::splat(x) }
unsafe fn trisaw(phase:S,color:S)->S {
    let check=phase.gt(color);
    check.select(v(1.0)-phase,phase)/check.select(v(1.0)-color,color)*v(2.0)-v(1.0)
}
unsafe fn tick(n:*mut Node,mode:u32,index:usize,seed:*mut [i64;2])->S {
    // Every fixed oscillator has at most seven unison lanes (mode mask <=0x600).
    core::hint::assert_unchecked(index<7);
    let color=input(n,2); let phase=input(n,1); let at=2+index*4;
    if index>0 { (*n).work[0]=(*n).work[0]*v(0.99588262365829742); }
    let mut p=(*n).work[at]+phase; p=p-p.floor();
    (*n).event=(*n).work[at+1].gt(p); (*n).work[at+1]=p;
    let frequency=(*n).work[0]+(*n).work[1];
    (*n).work[at]=(*n).work[at]+frequency;
    let c=color.clamp(v(1.0)-frequency,frequency);
    match mode&255 {
        0=>{ let t=color.clamp(v(1.0),frequency); p.lt(t).select(sin(p/t*v(6.2831853071693331)),S::zero()) },
        1=>{ let out=p+p-v(1.0); c.ge(v(0.5)).select(out,-out) },
        2=>p.lt(c).select(v(1.0),v(-1.0)),
        3=>trisaw(p,c),
        7=>{
            let out=sin(p*((*n).work[at+2]+v(1.0))*v(6.2831853071693331));
            if !(*n).event.is_zero() { (*n).work[at+2]=(*n).event.select((color*color*v(440.0)*(random(&mut *seed)+v(1.0))).floor(),(*n).work[at+2]); }
            out
        },
        8=>{
            if !(*n).event.is_zero() {
                (*n).work[at+2]=(*n).event.select((*n).work[at+3],(*n).work[at+2]);
                (*n).work[at+3]=(*n).event.select(random(&mut *seed),(*n).work[at+3]);
            }
            let out=lerp((*n).work[at+2],(*n).work[at+3],(v(1.0)-sin(p*v(3.1415926535846666)+v(1.5707963267923333)))*v(0.5));
            p.lt(color).select(out,(*n).work[at+3])
        },
        9=>{
            let factor=p.gt(v(0.5)).select(p.gt(v(0.75)).select(v(8.0),v(4.0)),v(2.0));
            p=p*factor; p=p-p.floor(); trisaw(p,c)
        },
        _=>super::fatal(),
    }
}
pub unsafe fn eidolon_oscillator_tick(n:*mut Node,state:*mut State,seed:*mut [i64;2],opcode:u32) {
    let mode=mode(n);
    if opcode==7 { (*n).work[1]=input(n,0)*v(0.5); }
    if (*n).last_tick&15==1 {
        if opcode==6 {
            (*n).work[0]=if mode&0x800!=0 {
                (*state).bpm*exp2((input(n,0)-v(0.5))*v(128.0)*v(0.083333313465118408))/v(2646000.0)
            } else { let t=input(n,0).max(S::zero()); t*t*t*t*t*v(0.0010000001639127731) };
            if (*n).work[31].is_zero() { (*n).work[31]=v(1.0); (*n).work[5]=random(&mut *seed); }
        } else {
            (*n).work[0]=if mode&0x800!=0 {
                (*(*state).voice).frequency*exp2((input(n,3)+input(n,4)*v(0.0099999979138374329))*v(128.0)*v(0.083333313465118408))
            } else { S::zero() };
            if (*n).work[31].is_zero() {
                (*n).work[31]=v(1.0);
                if mode&0x1000!=0 {
                    for i in 0..7 { (*n).work[5+i*4]=random(&mut *seed); (*n).work[2+i*4]=(*n).work[5+i*4].abs(); }
                }
            }
        }
    }
    if opcode==6 {
        (*n).out=tick(n,mode,0,seed);
        if mode&0x200==0 { (*n).out=((*n).out+if mode&0x100!=0 {v(-1.0)} else {v(1.0)})*v(0.5); }
        (*n).out=(*n).out*input(n,3);
    } else {
        (*n).out=S::zero(); let backup=(*n).work[0];
        for i in 0..=((mode&0x700)>>8) as usize { (*n).out=(*n).out+tick(n,mode,i,seed); }
        (*n).work[0]=backup; (*n).out=(*n).out*input(n,5);
    }
}
