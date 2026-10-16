//! Native graphics x87/SSE environment and transcendental helpers.
use std::{arch::asm, marker::PhantomData, rc::Rc};

#[cfg(not(any(target_arch = "x86", target_arch = "x86_64")))]
compile_error!("Recovered floating-point helpers require x86 or x86_64");

/// Scoped, thread-affine graphics FP state. Never move this guard to the synth thread.
pub struct GraphicsFp {
    cw: u16,
    mxcsr: u32,
    thread_affine: PhantomData<Rc<()>>,
}

impl GraphicsFp {
    pub fn enter() -> Self {
        let mut state = Self { cw: 0, mxcsr: 0, thread_affine: PhantomData };
        let cw = 0x027f_u16;
        let mxcsr = 0x1f80_u32;
        // All pointers are initialized, correctly sized stack locations.
        unsafe {
            asm!("fnstcw [{old_cw}]", "stmxcsr [{old_mx}]", "fldcw [{cw}]", "ldmxcsr [{mx}]",
                old_cw = in(reg) &mut state.cw, old_mx = in(reg) &mut state.mxcsr,
                cw = in(reg) &cw, mx = in(reg) &mxcsr, options(nostack));
        }
        state
    }
}

impl Drop for GraphicsFp {
    fn drop(&mut self) {
        unsafe {
            asm!("fldcw [{cw}]", "ldmxcsr [{mx}]",
                cw = in(reg) &self.cw, mx = in(reg) &self.mxcsr, options(nostack));
        }
    }
}

pub fn sqrt(value: f32) -> f32 {
    let mut result = 0.0_f32;
    unsafe {
        asm!("fld dword ptr [{value}]", "fsqrt", "fstp dword ptr [{result}]",
            value = in(reg) &value, result = in(reg) &mut result,
            out("st(0)") _, options(nostack));
    }
    result
}

pub fn atan2(y: f32, x: f32) -> f32 {
    let mut result = 0.0_f32;
    unsafe {
        asm!("fld dword ptr [{y}]", "fld dword ptr [{x}]", "fpatan", "fstp dword ptr [{result}]",
            y = in(reg) &y, x = in(reg) &x, result = in(reg) &mut result,
            out("st(0)") _, out("st(1)") _, options(nostack));
    }
    result
}

pub fn acos(value: f32) -> f32 {
    let mut result = 0.0_f32;
    unsafe {
        asm!("fld dword ptr [{value}]", "fld st(0)", "fmul st(0), st(0)",
            "fld1", "fsubrp st(1), st(0)", "fsqrt", "fxch st(1)", "fpatan",
            "fstp dword ptr [{result}]",
            value = in(reg) &value, result = in(reg) &mut result,
            out("st(0)") _, out("st(1)") _, out("st(2)") _, options(nostack));
    }
    result
}
