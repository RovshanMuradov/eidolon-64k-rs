//! Tape-stop/retrigger/shuffle/reverse with native node-local RNG ownership.
use super::graph::{Node,Context,State,input,mode};
use super::math::{Stereo as S,exp2,random,sample,lerp};
use core::ptr;
fn v(x:f64)->S { S::splat(x) }
unsafe fn write(n:*mut Node,x:S) {
    let index=(*n).work[0].ints(); let lanes=x.lanes(); let b=(*n).custom.cast::<[f64;2]>();
    (*b.add(index[0] as usize))[0]=lanes[0]; (*b.add(index[1] as usize))[1]=lanes[1];
}
pub unsafe fn eidolon_glitch_init(n:*mut Node,c:*mut Context) {
    (*n).custom=super::runtime::allocate(c,44100*8*core::mem::size_of::<S>());
}
pub unsafe fn eidolon_glitch_tick(n:*mut Node,state:*mut State,seed:*mut [i64;2]) {
    let mode=mode(n)&65535; let z=S::zero();
    if (*n).last_tick&15==1 {
        (*n).work[7]=super::arp::fraction(state,input(n,2))*v(0.5)*v(0.5);
        (*n).work[6]=input(n,3).clamp(v(1.0),z).left();
        (*n).work[2]=exp2(input(n,5)*v(128.0)*v(0.083333313465118408));
        match mode {
            0=>{ (*n).work[4]=(*n).work[6]*(*n).work[6]/(v(32768.0)*v(0.125)); (*n).work[5]=(input(n,4)*input(n,4)/(v(32768.0)*v(0.125))).left(); },
            1=>{ let sp=exp2(v(0.5)*input(n,4)); (*n).work[4]=sp.left(); (*n).work[5]=sp.right(); },
            2=>{ let sp=input(n,4).clamp(v(1.0),z); (*n).work[4]=sp.left(); (*n).work[5]=sp.right(); (*n).work[6]=(*n).work[6]*v(0.5); },
            3=>{}, _=>super::fatal(),
        }
        (*n).work[10]=v(44100.0)*v(8.0);
        *ptr::addr_of_mut!((*n).work[11]).cast::<*mut u8>()=(*n).custom;
    }
    let out=input(n,0);
    if mode>=2 {
        write(n,out); (*n).work[0]=(*n).work[0]+v(1.0);
        (*n).work[0]=(*n).work[0].ge((*n).work[10]).select((*n).work[0]-(*n).work[10],(*n).work[0]);
    }
    if !input(n,1).gt(v(0.5)).is_zero() {
        if (*n).event.is_zero() {
            (*n).event=v(1.0);
            if mode<2 { (*n).work[0]=z; }
            let rands=input(n,3).right();
            let local=ptr::addr_of_mut!((*n).work[21]).cast::<[i64;2]>();
            if !rands.is_zero() {
                let k=(rands*v(32768.0)).ints();
                let words=[k[0].wrapping_add(1023),1023,k[1],0];
                ptr::copy_nonoverlapping(words.as_ptr().cast::<u8>(),local.cast::<u8>(),16);
            } else { *local=*seed; }
            (*n).work[1]=(*n).work[0];
            for i in [3,16,17,9] { (*n).work[i]=z; }
            (*n).work[8]=v(1.0); (*n).work[12]=v(1.0); (*n).work[20]=v(32.0);
        }
        if mode<2 && !(*n).work[0].lt((*n).work[10]).is_zero() { write(n,out); (*n).work[0]=(*n).work[0]+v(1.0); }
        (*n).work[16]=sample((*n).custom.cast(),(*n).work[10],(*n).work[1]);
        (*n).work[17]=((*n).work[17]-v(1.0)).max(z);
        match mode {
            0=>{
                (*n).work[16]=(*n).work[1].lt((*n).work[0]).select((*n).work[16],out);
                (*n).work[12]=(*n).work[3].eq(z).select(((*n).work[12]-(*n).work[4]).max(z),(*n).work[12]);
                (*n).work[3]=(*n).work[12].eq(z).select(v(1.0),(*n).work[3]);
                (*n).work[12]=(*n).work[3].ne(z).select((*n).work[12]+(*n).work[5],(*n).work[12]);
                (*n).work[1]=((*n).work[1]+(*n).work[12]*(*n).work[2]).min((*n).work[10]);
            },
            1=>{
                let size=((*n).work[7].left()*(*n).work[8]).max(v(32.0));
                (*n).work[16]=lerp((*n).work[16],z,(((*n).work[1]-size*(*n).work[6])/v(32.0)).clamp(v(1.0),z));
                (*n).work[16]=lerp((*n).work[16],(*n).work[18],(*n).work[17]/v(32.0));
                if !(*n).work[1].ge(size).is_zero() {
                    (*n).work[1]=(*n).work[1]-size; (*n).work[12]=(*n).work[12]*(*n).work[5];
                    (*n).work[8]=((*n).work[8]*(*n).work[4]).clamp((*n).work[0],v(0.125));
                    (*n).work[18]=(*n).work[16]; (*n).work[17]=v(32.0);
                }
                (*n).work[1]=((*n).work[1]+(*n).work[12]*(*n).work[2]).min((*n).work[10]);
            },
            2=>{
                (*n).work[16]=lerp((*n).work[16],out,(*n).work[3]);
                (*n).work[16]=lerp((*n).work[16],(*n).work[18],(*n).work[17]/v(32.0));
                (*n).work[9]=(*n).work[9]-(*n).work[2];
                if !(*n).work[9].le(z).is_zero() {
                    (*n).work[1]=(*n).work[1]-(*n).work[12]; (*n).work[9]=(*n).work[12];
                    (*n).work[8]=(*n).work[8]-v(1.0); (*n).work[18]=(*n).work[16]; (*n).work[17]=v(32.0);
                }
                if !(*n).work[8].le(z).is_zero() {
                    let local=ptr::addr_of_mut!((*n).work[21]).cast::<[i64;2]>();
                    core::mem::swap(&mut *seed,&mut *local);
                    let r=random(&mut *seed).abs();
                    let other=(*n).work[7].shuffle((*n).work[7]);
                    (*n).work[12]=lerp((*n).work[7].min(other),(*n).work[7].max(other),r.left());
                    (*n).work[9]=(*n).work[12];
                    (*n).work[1]=(*n).work[0]-r.right()*(*n).work[6]*(*n).work[10]-v(1.0);
                    let r=random(&mut *seed).abs();
                    (*n).work[8]=(v(32.0)*r.left()*(*n).work[4]+v(1.0)).floor();
                    (*n).work[3]=r.right()*(*n).work[5];
                    core::mem::swap(&mut *seed,&mut *local);
                }
                (*n).work[1]=(*n).work[1]+(*n).work[2];
                (*n).work[1]=(*n).work[1].ge((*n).work[10]).select((*n).work[1]-(*n).work[10],(*n).work[1]);
            },
            3=>{ (*n).work[1]=(*n).work[1]-(*n).work[2]; (*n).work[1]=(*n).work[1].lt(z).select((*n).work[1]+(*n).work[10],(*n).work[1]); },
            _=>super::fatal(),
        }
    } else { (*n).event=z; (*n).work[20]=((*n).work[20]-v(1.0)).max(z); }
    (*n).out=lerp(out,(*n).work[16],(*n).work[20]/v(32.0));
}
