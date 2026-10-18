//! Complete recovered tick bodies for the incrementally ported node types.
//! Input calls, cache timing, coefficient cadence and arithmetic order are preserved.
use super::graph::{self, Node, State, call_input, input, cached, mode};
use super::math::{Stereo as S, exp2, lerp};
fn v(x: f64) -> S { S::splat(x) }

#[inline(never)]
unsafe fn adsr_map(x: S) -> S {
    let t = x.max(S::zero());
    v(1.0) / (t * t * t * v(418381.75) + v(1.0))
}

unsafe fn adsr(n: *mut Node, state: *mut State) {
    let mode = mode(n);
    let z = S::zero();
    if (*n).last_tick & 15 == 1 {
        (*n).work[8] = if mode & 0x80 != 0 { exp2((input(n,4)-v(0.75))*v(128.0)/v(6.0)) } else { input(n,4) };
    }
    let tmask = (*(*state).voice).trigger.ge(v(0.5));
    if !tmask.is_zero() {
        (*n).work[0] = tmask.select(v(0.5), (*n).work[0]);
        (*n).work[1] = tmask.select(z, (*n).work[1]);
        (*n).work[2] = tmask.select(adsr_map(input(n,0)), (*n).work[2]);
    }
    let rmask = (*(*state).voice).gate.lt(v(0.5));
    let rbmask = (*n).work[0].le(v(2.0)) & rmask;
    if !rbmask.is_zero() {
        (*n).work[0] = rbmask.select(v(10.0), (*n).work[0]);
        let rr = adsr_map(input(n,3));
        (*n).work[2] = rbmask.select(rr * (*n).work[1], (*n).work[2]);
        (*n).work[4] = rbmask.select(exp2(rr*v(-10.0)), (*n).work[4]);
    }
    let released = if mode & 0x40 != 0 { (*n).work[1]*(*n).work[4] } else { ((*n).work[1]-(*n).work[2]).max(z) };
    (*n).work[1] = rmask.select(released, (*n).work[1]);
    let sustain = input(n,2).max(z);
    let smask = (*n).work[0].ne(v(2.0));
    if !smask.is_zero() {
        let mut dmask = (*n).work[0].eq(v(1.0));
        if mode & 0x40 != 0 {
            (*n).work[5] = dmask.select((*n).work[5]*(*n).work[4], (*n).work[5]);
            (*n).work[1] = dmask.select(lerp(sustain,v(1.0),(*n).work[5]),(*n).work[1]);
        } else {
            (*n).work[1] = dmask.select(((*n).work[1]-(*n).work[2]).max(sustain),(*n).work[1]);
        }
        dmask = (*n).work[1].le(sustain+v(0.0000152587890625)) & dmask;
        (*n).work[0] = dmask.select(v(2.0),(*n).work[0]);
        let mut amask = (*n).work[0].eq(v(0.5));
        (*n).work[1] = amask.select(((*n).work[1]+(*n).work[2]).min(v(1.0)),(*n).work[1]);
        amask = (*n).work[1].eq(v(1.0)) & amask;
        if !amask.is_zero() {
            (*n).work[0] = amask.select(v(1.0),(*n).work[0]);
            let rr = adsr_map(input(n,1));
            (*n).work[2] = amask.select(rr*(v(1.0)-sustain),(*n).work[2]);
            (*n).work[4] = amask.select(exp2(rr*v(-10.0)),(*n).work[4]);
            (*n).work[5] = amask.select(v(1.0),(*n).work[5]);
        }
    } else { (*n).work[1] = sustain; }
    (*n).event = (*n).work[0].eq(v(0.5)) | (*n).work[1].gt(v(0.0000152587890625));
    (*n).out = (*n).work[1]*(*n).work[8];
}

pub unsafe fn eidolon_node_tick(n: *mut Node, state: *mut State, opcode: u32) {
    let z = S::zero();
    // Constants and voice parameters are deliberately stateless in the source.
    if opcode == 64 { return; }
    if opcode == 29 { (*n).out=(*state).midi[(mode(n)&65535) as usize]*input(n,0); return; }
    if opcode == 65 {
        let params = (*state).voice.cast::<S>();
        (*n).out = input(n,0) * *params.add((*n).id as usize - 64 + 2);
        return;
    }
    // CHANNELROOT executes its envelope update even when MUL hits the tick cache.
    if opcode == 1 {
        if !(*n).work[0].is_zero() {
            if !cached(n,state) {
                call_input(n,0);call_input(n,1);
                eidolon_node_tick(n,state,15);
            }
            let a = (*n).out.abs();
            (*n).work[1] = v(0.99994754791259766)*((*n).work[1]-a)+a;
            (*n).work[0] = (*n).work[1].gt(v(1.0000003385357559e-5));
        }
        return;
    }
    if opcode == 28 {
        call_input(n,1);
        (*n).out=if !input(n,1).ge(v(0.5)).is_zero() { call_input(n,0); input(n,0) } else { z };
        return;
    }
    if opcode == 5 { adsr(n,state); return; }
    if opcode == 2 {
        for i in (0..(*n).num_inputs as usize).rev() { call_input(n,i); }
        (*n).out = z;
        for i in (0..(*n).num_inputs as usize).rev() { (*n).out = (*n).out + input(n,i); }
        return;
    }
    let count = match opcode { 4|20|23|30 => 3, 22|27|39|45 => 1, _ => 2 };
    let a = input(n,0);
    let b = if count > 1 { input(n,1) } else { z };
    let update = (*n).last_tick & 15 == 1;
    (*n).out = match opcode {
        4 => { (*n).event = input(n,2).ne(z); a*b },
        10|11 => {
            if update {
                let f = b.clamp(v(1.0),v(-1.0));
                if opcode == 10 { (*n).work[0] = v(1.0)-f.abs(); (*n).work[1] = f; }
                else { (*n).work[0] = v(1.0)/(v(1.0)+f.abs()); (*n).work[1] = -f*(*n).work[0]; }
            }
            let out = (*n).work[0]*a + (*n).work[1]*(*n).work[2];
            (*n).work[2] = if opcode == 10 { out } else { a };
            out
        },
        13 => {
            if update { let r=b.clamp(v(1.0),z); (*n).work[0]=(v(1.0)-r).shuffle(r).sqrt(); }
            a*(*n).work[0]
        },
        15 => a*b,
        16 => b.ne(z).select(a/b,z),
        17 => a+b,
        18 => a-b,
        19 => a.clamp(b.abs(),-b.abs()),
        20 => lerp(a,b,input(n,2)),
        // Preserve the full recovered DWORD read, including the adjacent patch word.
        22 => if mode(n) != 0 { a.right() } else { a.left() },
        23 => {
            if update {
                (*n).work[0] = exp2((v(-4.6051701859687455)/(b.max(v(0.0010000001639127731))*v(5644.796875)))*v(1.4426950408815173));
                (*n).work[1] = exp2((v(-4.6051701859687455)/(input(n,2).max(v(0.0010000001639127731))*v(5644.796875)*v(10.0)))*v(1.4426950408815173));
            }
            let a=a.abs();
            a.gt((*n).out).select((*n).work[0],(*n).work[1])*((*n).out-a)+a
        },
        25 => a.gt(b).select(v(1.0),z), // Fixed patch contains only COMPARE mode 0.
        27 => (*(*n).inputs[0]).event.ne(z)&v(1.0),
        30 => {
            let kind=mode(n)&65535;
            if update {
                let threshold=exp2((input(n,2)-v(0.75))*v(128.0)/v(6.0));
                (*n).work[2]=v(1.0)/threshold; (*n).work[3]=threshold;
                let mut t=b.max(z);
                match kind {
                    0|1=>{ t=if kind==0 { t.min(v(0.997650146484375)).sqrt() } else { -t.min(v(0.997650146484375)) }; (*n).work[0]=(t+t)/(v(1.0)-t); },
                    3=>{ (*n).work[0]=exp2(-(t*t*v(8.0))); },
                    _=>super::fatal(),
                }
            }
            let d=a*(*n).work[2];
            let out=match kind {
                0=>(v(1.0)+(*n).work[0])*d/(v(1.0)+(*n).work[0]*d.abs()),
                1=>(v(1.0)+(*n).work[0])*d/(v(1.0)+(*n).work[0]*d.abs().min(v(1.0))),
                3=>d.abs().gt((*n).work[0]).select(d.gt(z).select(v(1.0),v(-1.0)),d/(*n).work[0]),
                _=>super::fatal(),
            };
            out*(*n).work[3]
        },
        34 => { let out=a-(*n).work[0]+b.min(v(0.99994754791259766))*(*n).out; (*n).work[0]=a; out },
        39 => {
            let mask=a.ge(v(0.5))&(*n).work[0].eq(z);
            (*n).work[0]=mask.select(v(1.0),(*n).work[0]);
            (*n).work[0]=a.lt(v(0.5)).select(z,(*n).work[0]);
            mask.select(v(1.0),z)
        },
        45 => -a,
        47 => a.min(b),
        48 => a.max(b),
        _ => super::fatal(),
    };
}

// Keep the graph module publicly usable without importing raw callback helpers twice.
const _: usize = core::mem::size_of::<graph::Node>();
