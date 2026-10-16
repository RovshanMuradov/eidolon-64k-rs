//! Recovered delay, reverb, compressor and biquad DSP; no host libm or fused operations.
use super::graph::{Context,Node,State,cached,call_input,input,mode};
use super::math::{Stereo as S,exp2,log2,sin,lerp};
fn v(x:f64)->S { S::splat(x) }
unsafe fn read(buffer:*mut [f64;2],index:S)->S {
    let p=index.ints();
    S::load([(*buffer.add(p[0] as usize))[0],(*buffer.add(p[1] as usize))[1]].as_ptr())
}
unsafe fn write(buffer:*mut [f64;2],index:S,value:S) {
    let p=index.ints(); let lanes=value.lanes();
    (*buffer.add(p[0] as usize))[0]=lanes[0]; (*buffer.add(p[1] as usize))[1]=lanes[1];
}
unsafe fn advance(n:*mut Node,value:S) {
    write((*n).custom.cast(),(*n).work[0],value);
    for i in 0..2 {
        let next=(*n).work[i]+v(1.0);
        (*n).work[i]=next.ge((*n).work[10]).select(next-(*n).work[10],next);
    }
}
unsafe fn delay_params(n:*mut Node,state:*mut State,allpass:bool,mode:u32) {
    let mut temp=input(n,1).max(S::zero());
    temp=match mode&15 {
        0=>super::arp::fraction(state,temp),
        1=>temp*v(1640.0),
        2=>temp*v(5644.796875),
        3=>temp*(v(44100.0)*v(2.0)),
        4=>(v(1.0)/(*(*state).voice).frequency)*exp2((temp-v(0.5))*v(128.0)*v(0.083333313465118408)),
        5=>(v(1.0)/(*(*state).voice).frequency)*temp,
        _=>temp,
    };
    (*n).work[10]=v(44100.0)*v(4.0);
    let mut pos=(*n).work[10]+v(1.0)+(*n).work[0]-temp.clamp((*n).work[10]-v(1.0),v(4.0));
    if allpass {
        pos=pos+v(1.0);
        (*n).work[1]=pos.floor();
        let mut alpha=v(1.0)+(*n).work[1]-pos;
        let mask=alpha.lt(v(0.5));
        alpha=mask.select(alpha+v(1.0),alpha);
        (*n).work[1]=mask.select((*n).work[1]+v(1.0),(*n).work[1]);
        (*n).work[1]=(*n).work[1].ge((*n).work[10]).select((*n).work[1]-(*n).work[10],(*n).work[1]);
        (*n).work[2]=(v(1.0)-alpha)/(v(1.0)+alpha);
    } else {
        pos=pos.ge((*n).work[10]).select(pos-(*n).work[10],pos);
        (*n).work[1]=pos.floor(); (*n).work[2]=pos-(*n).work[1];
    }
}
unsafe fn delay(n:*mut Node,state:*mut State,opcode:u32) {
    let mode=mode(n);
    if (*n).last_tick&15==1 {
        delay_params(n,state,opcode!=51,mode);
        if opcode==33 {
            (*n).work[5]=input(n,3).clamp(v(1.0),S::zero());
            (*n).work[7]=input(n,2).clamp(v(0.997650146484375),S::zero());
            (*n).work[8]=input(n,4).clamp(v(1.0),S::zero());
        }
    }
    let value=read((*n).custom.cast(),(*n).work[1]);
    if opcode==51 {
        advance(n,input(n,0));
        (*n).out=lerp(value,read((*n).custom.cast(),(*n).work[1]),(*n).work[2]);
    } else {
        if opcode==32 { advance(n,input(n,0)); }
        (*n).work[4]=(*n).work[3]+(value-(*n).work[4])*(*n).work[2];
        (*n).work[3]=value;
        if opcode==33 {
            let feedback=input(n,0)+(*n).work[4]*(*n).work[7];
            (*n).work[6]=feedback+(*n).work[5]*((*n).work[6]-feedback);
            let mut value=(*n).work[6];
            if mode&0x80!=0 { value=value.shuffle(value); }
            advance(n,value);
            (*n).out=lerp(input(n,0),(*n).work[4],(*n).work[8]);
        } else { (*n).out=(*n).work[4]; }
    }
}
unsafe fn reverb(n:*mut Node) {
    let x=input(n,0); let gain=input(n,1);
    let summed=(x.left()+x.right())*(gain*gain*gain).max(S::zero());
    let feedback=input(n,2).max(S::zero())*v(0.28125)+v(0.703125);
    let damp=input(n,3).clamp(v(1.0),S::zero());
    let mut sum=S::zero(); let mut offset=S::zero();
    let mut lr=S::load([0.0,23.0].as_ptr());
    let lengths=[225.0,341.0,441.0,556.0,1116.0,1188.0,1277.0,1356.0,1422.0,1491.0,1557.0,1617.0];
    for i in (0..12).rev() {
        let pos=offset+(*n).work[i];
        let out=read((*n).custom.cast(),pos);
        let value=if i>3 {
            sum=sum+out;
            let value=summed+out*feedback;
            (*n).work[i+8]=value+damp*((*n).work[i+8]-value);
            (*n).work[i+8]
        } else {
            let value=sum+out*v(0.61799955368041992);
            sum=out-value*v(0.61799955368041992); value
        };
        write((*n).custom.cast(),pos,value);
        let next=(*n).work[i]+v(1.0);
        (*n).work[i]=next.lt(v(lengths[i])+lr).select(next,S::zero());
        offset=offset+v(1640.0); lr=lr.shuffle(lr);
    }
    (*n).event=sum-(*n).work[31]+v(0.99432373046875)*(*n).event;
    (*n).work[31]=sum;
    let width=input(n,5).clamp(v(1.0),S::zero());
    let wet1=(v(1.0)+width)*v(0.5); let wet2=(v(1.0)-width)*v(0.5);
    (*n).out=lerp(x,(*n).event*wet1+(*n).event.shuffle((*n).event)*wet2,input(n,4).clamp(v(1.0),S::zero()));
}
unsafe fn compressor(n:*mut Node) {
    if (*n).last_tick&15==1 {
        (*n).work[0]=exp2((v(-4.6051701859687455)/(input(n,4).max(v(1.0000003385357559e-5))*v(5644.796875)))*v(1.4426950408815173));
        (*n).work[1]=exp2((v(-4.6051701859687455)/(input(n,5).max(v(1.0000003385357559e-5))*v(5644.796875)*v(10.0)))*v(1.4426950408815173));
        (*n).work[2]=exp2(input(n,3)*v(6.0));
        (*n).work[3]=(input(n,2)-v(0.75))*v(128.0);
    }
    let db=log2(input(n,1).abs()+v(1.0000003385357559e-5))*v(6.0);
    (*n).work[4]=db.gt((*n).work[4]).select((*n).work[0],(*n).work[1])*((*n).work[4]-db)+db;
    let delta=(*n).work[4]-(*n).work[3];
    let comp=(*n).work[2].le(v(1.0)); let flag=delta.gt(S::zero());
    let mask=(comp&flag)|!(comp|flag);
    let mut gain=v(1.0);
    if !mask.is_zero() { gain=mask.select(exp2(delta*((*n).work[2]-v(1.0))/v(6.0)),gain); }
    (*n).out=input(n,0)*gain;
}
pub unsafe fn frequency_map(x:S,state:*mut State,mode:u32)->S {
    if mode&0x80!=0 { (*(*state).voice).frequency*v(2.0) }
    else if mode&0x40!=0 { (x*x).clamp(v(0.997650146484375),S::zero()) }
    else { (v(1.0)/exp2((v(1.0)-x)*v(10.0))).min(v(0.997650146484375)) }
}
unsafe fn biquad(n:*mut Node,state:*mut State) {
    let mode=mode(n); let kind=mode&15;
    if (*n).last_tick&15==1 {
        let w=v(3.1415926535846666)*frequency_map(input(n,1),state,mode);
        let sw=sin(w); let mut cw=sin(w+v(1.5707963267923333));
        let mut q=exp2(input(n,2)*v(10.0)); let alpha=sw/(q+q);
        let mut a=S::zero(); let mut beta=S::zero();
        if kind<6 { (*n).work[3]=v(1.0)+alpha; (*n).work[5]=v(1.0)-alpha; (*n).work[4]=-(cw+cw); }
        else if kind<9 { a=exp2(v(0.5)*(input(n,3)-v(0.75))*v(128.0)/v(6.0)); beta=a.sqrt()*sw/q; }
        else { q=input(n,2).min(v(0.99994754791259766)); (*n).work[3]=v(1.0); (*n).work[4]=q*-(cw+cw); (*n).work[5]=q*q; (*n).work[1]=S::zero(); }
        match kind {
            0=>{ (*n).work[0]=(v(1.0)-cw)*v(0.5); (*n).work[2]=(*n).work[0]; (*n).work[1]=v(1.0)-cw; },
            1=>{ (*n).work[0]=(v(1.0)+cw)*v(0.5); (*n).work[2]=(*n).work[0]; (*n).work[1]=-(v(1.0)+cw); },
            2|3=>{ (*n).work[0]=if kind==2 { sw*v(0.5) } else { alpha }; (*n).work[2]=-(*n).work[0]; (*n).work[1]=S::zero(); },
            4=>{ (*n).work[0]=v(1.0); (*n).work[2]=v(1.0); (*n).work[1]=(*n).work[4]; },
            5=>{ (*n).work[0]=(*n).work[5]; (*n).work[2]=(*n).work[3]; (*n).work[1]=(*n).work[4]; },
            6=>{ (*n).work[0]=v(1.0)+alpha*a; (*n).work[2]=v(1.0)-alpha*a; (*n).work[3]=v(1.0)+alpha/a; (*n).work[5]=v(1.0)-alpha/a; (*n).work[4]=-(cw+cw); (*n).work[1]=(*n).work[4]; },
            7|8=>{
                if kind==7 { cw=-cw; } let ap=a+v(1.0); let am=a-v(1.0);
                (*n).work[0]=a*(ap+am*cw+beta); (*n).work[2]=a*(ap+am*cw-beta);
                (*n).work[3]=ap-am*cw+beta; (*n).work[5]=ap-am*cw-beta;
                let b1=a*(am+ap*cw)*v(2.0); let a1=(am-ap*cw)*v(2.0);
                (*n).work[1]=if kind==7 { b1 } else { -b1 }; (*n).work[4]=if kind==7 { -a1 } else { a1 };
            },
            9=>{ (*n).work[0]=v(1.0); (*n).work[2]=S::zero(); },
            10=>{ (*n).work[0]=v(0.5)-v(0.5)*(*n).work[5]; (*n).work[2]=-(*n).work[0]; },
            _=>{},
        }
        let inv=v(1.0)/(*n).work[3];
        for i in [0,1,2,4,5] { (*n).work[i]=(*n).work[i]*inv; }
    }
    let stages=((mode&0xf00)>>7).max(1) as usize;
    let mut x=input(n,0);
    for i in 0..stages {
        let at=6+2*i; let out=(*n).work[0]*x+(*n).work[at];
        (*n).work[at]=(*n).work[1]*x-(*n).work[4]*out+(*n).work[at+1];
        (*n).work[at+1]=(*n).work[2]*x-(*n).work[5]*out;
        x=out;
    }
    (*n).out=x;
}

unsafe fn state_variable(n:*mut Node,state:*mut State) {
    let mode=mode(n);
    if (*n).last_tick&15==1 {
        (*n).work[0]=frequency_map(input(n,1),state,mode);
        if mode&0x80!=0 { (*n).work[0]=(*n).work[0]*v(1.5707963267923333); }
        (*n).work[1]=(v(1.0)-input(n,2)).clamp(v(0.997650146484375),S::zero());
    }
    let mut x=input(n,0);
    for stage in 0..((mode&0xf00)>>7).max(1) as usize {
        let at=4+3*stage;
        for _ in 0..2 {
            (*n).work[at]=(*n).work[at]+(*n).work[0]*(*n).work[at+2];
            (*n).work[at+1]=x-(*n).work[at]-(*n).work[1]*(*n).work[at+2];
            (*n).work[at+2]=(*n).work[at+2]+(*n).work[0]*(*n).work[at+1];
        }
        x=S::zero();
        if mode&1!=0 { x=x+(*n).work[at]; }
        if mode&2!=0 { x=x+(*n).work[at+1]; }
        if mode&4!=0 { x=x+(*n).work[at+2]; }
        if mode&8!=0 { x=x-(*n).work[at+1]; }
    }
    (*n).out=x;
}

#[no_mangle]
pub unsafe extern "C" fn eidolon_formant_tick(n:*mut Node,c:*mut Context) {
    if cached(n,(*c).state) { return; }
    call_input(n,0); call_input(n,1);
    if (*n).event.is_zero() {
        (*n).event=v(1.0);
        (*n).custom=((*c).alloc)(125*5*core::mem::size_of::<S>());
        let buffer=(*n).custom.cast::<S>();
        for vowel in 0..25 {
            for filter in 0..5 {
                let at=vowel*15+filter;
                let amp=v(super::formants::COEFFICIENTS[at] as f64);
                let bw=v(super::formants::COEFFICIENTS[at+5] as f64);
                let frequency=v(super::formants::COEFFICIENTS[at+10] as f64);
                let r=exp2((-(bw*v(3.1415926535846666)/v(44100.0)))*v(1.4426950408815173));
                let coeff_c=-(r*r);
                let coeff_b=r*v(2.0)*sin(frequency*v(6.2831853071693331)/v(44100.0)+v(1.5707963267923333));
                let p=buffer.add((vowel*5+filter)*5);
                *p=(v(1.0)-coeff_b-coeff_c)*exp2(-amp/v(6.0));
                *p.add(1)=coeff_b; *p.add(2)=coeff_c;
            }
        }
    }
    (*n).out=S::zero();
    let buffer=(*n).custom.cast::<S>().add((mode(n)&65535) as usize*25);
    for filter in 0..5 {
        let p=buffer.add(filter*5);
        let y=input(n,0)*(*p)+(*p.add(3))*(*p.add(1))+(*p.add(4))*(*p.add(2));
        *p.add(4)=*p.add(3); *p.add(3)=y;
        (*n).out=(*n).out+y*input(n,1);
    }
}

#[no_mangle]
pub unsafe extern "C" fn eidolon_effect_tick(n:*mut Node,state:*mut State,opcode:u32) {
    if cached(n,state) { return; }
    let count=match opcode { 9=>4,32|51=>2,33=>5,36|38=>6,43=>3,_=>std::process::abort() };
    for i in 0..count { call_input(n,i); }
    match opcode { 9=>biquad(n,state),32|33|51=>delay(n,state,opcode),36=>reverb(n),38=>compressor(n),43=>state_variable(n,state),_=>unreachable!() }
}
#[no_mangle]
pub unsafe extern "C" fn eidolon_effect_init(n:*mut Node,c:*mut Context,opcode:u32) {
    let count=if opcode==36 { 1640*12 } else { 44100*4 };
    (*n).custom=((*c).alloc)(core::mem::size_of::<S>()*count);
}
