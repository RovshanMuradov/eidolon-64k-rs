//! Recovered noise, one-shot random, sample-bank node and sampler ticks.
use super::graph::{Node,State,cached,call_input,input,mode};
use super::math::{Stereo as S,random,sample,exp2,lerp};
use core::ptr;
fn v(x:f64)->S { S::splat(x) }
unsafe fn buffer(n:*mut Node)->*mut [f64;2] { *ptr::addr_of!((*n).work[11]).cast::<*mut [f64;2]>() }

#[no_mangle]
pub unsafe extern "C" fn eidolon_random_tick(n:*mut Node,state:*mut State,seed:*mut [i64;2],opcode:u32) {
    if opcode==35 {
        if (*n).out.is_zero() { call_input(n,0); (*n).out=random(&mut *seed)*input(n,0); }
        return;
    }
    if cached(n,state) { return; }
    call_input(n,0); call_input(n,1);
    let white=random(&mut *seed); let mut mix=input(n,0);
    let out=if mix.is_zero() { white } else {
        (*n).work[0]=(*n).work[0]*v(0.997650146484375)+white*v(0.099045991897583008);
        (*n).work[1]=(*n).work[1]*v(0.96299982070922852)+white*v(0.29651640355587006);
        (*n).work[2]=(*n).work[2]*v(0.57000017166137695)+white*v(1.0526914596557617);
        let pink=(((*n).work[0]+(*n).work[1]+(*n).work[2]+white*v(0.18479990959167480))*v(0.19999992847442627)).clamp(v(1.0),v(-1.0));
        let mut last=white; let mut mask=S::zero().eq(S::zero());
        loop {
            last=last*(v(0.125)*v(0.5)); (*n).work[3]=(*n).work[3]+(last&mask);
            mask=(*n).work[3].abs().gt(v(1.0));
            if mask.is_zero() { break; }
            (*n).work[3]=(*n).work[3]-(last&mask); last=random(&mut *seed);
        }
        mix=mix+mix;
        mix.gt(v(1.0)).select(lerp(pink,(*n).work[3],mix-v(1.0)),lerp(white,pink,mix))
    };
    (*n).out=out*input(n,1);
}
#[no_mangle]
pub unsafe extern "C" fn eidolon_bank_tick(n:*mut Node,state:*mut State,counts:*const u32,buffers:*const *mut [f64;2]) {
    if cached(n,state) { return; }
    let id=(mode(n)&65535) as usize;
    (*n).work[10]=v(*counts.add(id) as f64);
    *ptr::addr_of_mut!((*n).work[11]).cast::<*mut [f64;2]>()=*buffers.add(id);
}
#[no_mangle]
pub unsafe extern "C" fn eidolon_sampler_tick(n:*mut Node,state:*mut State) {
    if cached(n,state) { return; }
    for i in 0..7 { call_input(n,i); }
    let mode=mode(n); let z=S::zero();
    if (*n).last_tick&15==1 {
        let source=(*n).inputs[0];
        (*n).work[10]=(*source).work[10];
        *ptr::addr_of_mut!((*n).work[11]).cast::<*mut [f64;2]>()=buffer(source);
        let length=(*n).work[10];
        (*n).work[5]=(input(n,1)*length).clamp(length-v(1.0),z);
        let start=(input(n,4)*length).clamp(length-v(1.0),z);
        let end=(input(n,5)*length).clamp(length-v(1.0),z);
        (*n).work[1]=start.min(end); (*n).work[2]=start.max(end);
        (*n).work[3]=(((*n).work[2]-(*n).work[1])*v(0.5)*input(n,6).clamp(v(1.0),z)).max(v(1.0));
        (*n).work[9]=exp2(input(n,2)*v(128.0)*v(0.083333313465118408));
    }
    (*n).out=z;
    let forward=input(n,3).lt(v(0.5)); let direction=forward.select(v(1.0),v(-1.0));
    let step=(*n).work[9]*direction;
    (*n).work[0]=(*n).work[0]+(*n).work[5];
    let mut out=sample(buffer(n),(*n).work[10],(*n).work[0]);
    if mode&8!=0 {
        (*n).work[4]=(*n).work[4]|((*n).work[0].ge((*n).work[1])&(*n).work[0].le((*n).work[2]));
        if !(*n).work[4].is_zero() {
            (*n).work[0]=(*n).work[0].clamp((*n).work[2],(*n).work[1]);
            let boundary=forward.select((*n).work[2],(*n).work[1]);
            let other=forward.select((*n).work[1],(*n).work[2])+(*n).work[3]*direction;
            let distance=boundary-(*n).work[0];
            let far=sample(buffer(n),(*n).work[10],other-distance);
            out=(*n).work[4].select(lerp(far,out,distance.abs().min((*n).work[3])/(*n).work[3]),out);
            (*n).work[0]=(*n).work[0]+step;
            let distance=boundary-(*n).work[0];
            (*n).work[0]=((*n).work[4]&(distance*direction).lt(z)).select(other-distance,(*n).work[0]);
        } else { (*n).work[0]=(*n).work[0]+step; }
    } else { (*n).work[0]=(*n).work[0]+step; }
    (*n).work[0]=(*n).work[0].clamp((*n).work[10],v(-1.0));
    (*n).out=((*n).work[0].ge((*n).work[10])|(*n).work[0].lt(z)).select(z,out);
    (*n).work[0]=(*n).work[0]-(*n).work[5];
}
