//! SSE operation order from pinned sample_t.cpp, and Sampler_Sample.
//! Requires SSE4.1. Synthesis runs with MXCSR=0xffc0; initialization uses 0x1f80.
//! Explicit intrinsics retain native conversions, lane order, and separate mul/add.
#![allow(clippy::missing_safety_doc)]
#[cfg(target_arch = "x86")]
use core::arch::x86::*;
#[cfg(target_arch = "x86_64")]
use core::arch::x86_64::*;

#[derive(Clone, Copy)]
#[repr(transparent)]
pub struct Stereo(pub __m128d);

impl Stereo {
    #[inline]
    pub fn splat(x: f64) -> Self { unsafe { Self(_mm_set1_pd(x)) } }
    #[inline]
    pub fn zero() -> Self { unsafe { Self(_mm_setzero_pd()) } }
    #[inline]
    pub unsafe fn abs(self) -> Self { Self(_mm_andnot_pd(_mm_set1_pd(-0.0), self.0)) }
    #[inline]
    pub unsafe fn min(self, b: Self) -> Self { Self(_mm_min_pd(self.0, b.0)) }
    #[inline]
    pub unsafe fn max(self, b: Self) -> Self { Self(_mm_max_pd(self.0, b.0)) }
    #[inline]
    pub unsafe fn eq(self, b: Self) -> Self { Self(_mm_cmpeq_pd(self.0, b.0)) }
    #[inline]
    pub unsafe fn ne(self, b: Self) -> Self { Self(_mm_cmpneq_pd(self.0, b.0)) }
    #[inline]
    pub unsafe fn lt(self, b: Self) -> Self { Self(_mm_cmplt_pd(self.0, b.0)) }
    #[inline]
    pub unsafe fn le(self, b: Self) -> Self { Self(_mm_cmple_pd(self.0, b.0)) }
    #[inline]
    pub unsafe fn gt(self, b: Self) -> Self { Self(_mm_cmpgt_pd(self.0, b.0)) }
    #[inline]
    pub unsafe fn ge(self, b: Self) -> Self { Self(_mm_cmpge_pd(self.0, b.0)) }
    #[inline]
    pub unsafe fn select(self, yes: Self, no: Self) -> Self { Self(_mm_blendv_pd(no.0, yes.0, self.0)) }
    #[inline]
    pub unsafe fn is_zero(self) -> bool { _mm_testz_si128(_mm_castpd_si128(self.0), _mm_castpd_si128(self.0)) != 0 }
    #[inline]
    pub unsafe fn sqrt(self) -> Self { Self(_mm_sqrt_pd(self.0)) }
    #[inline]
    pub unsafe fn shuffle(self, b: Self) -> Self { Self(_mm_shuffle_pd::<1>(self.0, b.0)) }
    #[inline]
    pub unsafe fn left(self) -> Self { Self(_mm_unpacklo_pd(self.0, self.0)) }
    #[inline]
    pub unsafe fn right(self) -> Self { Self(_mm_unpackhi_pd(self.0, self.0)) }
    #[inline]
    pub unsafe fn clamp(self, high: Self, low: Self) -> Self { low.max(high.min(self)) }
    #[inline]
    pub unsafe fn floor(self) -> Self { Self(_mm_floor_pd(self.0)) }
    #[inline]
    pub unsafe fn ints(self) -> [i32; 4] {
        let mut out=[0;4]; _mm_storeu_si128(out.as_mut_ptr().cast(),_mm_cvtpd_epi32(self.0)); out
    }
    #[inline]
    pub unsafe fn lanes(self) -> [f64; 2] { let mut out=[0.0;2]; self.store(out.as_mut_ptr()); out }
    #[inline]
    pub unsafe fn load(p: *const f64) -> Self { Self(_mm_loadu_pd(p)) }
    #[inline]
    pub unsafe fn store(self, p: *mut f64) { _mm_storeu_pd(p, self.0) }
}

macro_rules! arithmetic {
    ($trait:ident, $method:ident, $intrinsic:ident) => {
        impl core::ops::$trait for Stereo {
            type Output = Self;
            #[inline] fn $method(self, b: Self) -> Self { unsafe { Self($intrinsic(self.0, b.0)) } }
        }
    };
}
arithmetic!(Add, add, _mm_add_pd);
arithmetic!(Sub, sub, _mm_sub_pd);
arithmetic!(Mul, mul, _mm_mul_pd);
arithmetic!(Div, div, _mm_div_pd);
arithmetic!(BitAnd, bitand, _mm_and_pd);
arithmetic!(BitOr, bitor, _mm_or_pd);
impl core::ops::Neg for Stereo {
    type Output = Self;
    #[inline] fn neg(self) -> Self { unsafe { Self(_mm_xor_pd(self.0, _mm_set1_pd(-0.0))) } }
}
impl core::ops::Not for Stereo {
    type Output = Self;
    #[inline] fn not(self) -> Self { unsafe { Self(_mm_xor_pd(self.0, _mm_castsi128_pd(_mm_set1_epi32(-1)))) } }
}
#[inline]
pub fn lerp(a: Stereo, b: Stereo, f: Stereo) -> Stereo { (b - a) * f + a }

#[target_feature(enable = "sse4.1")]
pub unsafe fn exp2(x: Stereo) -> Stereo {
    let k = _mm_cvtpd_epi32(x.0);
    let p = _mm_sub_pd(x.0, _mm_cvtepi32_pd(k));
    let mut r = _mm_set1_pd(0.00015465324084118492);
    for c in [0.0013395291543787380, 0.0096180399117429261,
              0.055503406540083233, 0.24022651101404335,
              0.69314720007241704, 0.99999999997089617] {
        r = _mm_add_pd(_mm_mul_pd(r, p), _mm_set1_pd(c));
    }
    let k = _mm_add_epi32(k, _mm_set_epi32(0, 0, 1023, 1023));
    let k = _mm_shuffle_epi32::<0x72>(_mm_slli_epi32::<20>(k));
    Stereo(_mm_mul_pd(r, _mm_castsi128_pd(k)))
}

#[target_feature(enable = "sse4.1")]
pub unsafe fn log2(x: Stereo) -> Stereo {
    let bits = _mm_castpd_si128(x.0);
    let minexp = _mm_set_epi32(0, 1023, 0, 1023);
    let exponent = _mm_shuffle_epi32::<0x78>(_mm_sub_epi64(_mm_srli_epi64::<52>(bits), minexp));
    let p = _mm_or_pd(
        _mm_and_pd(x.0, _mm_castsi128_pd(_mm_set1_epi64x(0x000f_ffff_ffff_ffff))),
        _mm_castsi128_pd(_mm_slli_epi64::<52>(minexp)),
    );
    let y = _mm_div_pd(_mm_sub_pd(p, _mm_set1_pd(1.0)), _mm_add_pd(p, _mm_set1_pd(1.0)));
    let y2 = _mm_mul_pd(y, y);
    let mut r = _mm_set1_pd(0.41098153827988426);
    for c in [0.40215548317064531, 0.57755014627036871, 0.96178780600166647, 2.8853901278343983] {
        r = _mm_add_pd(_mm_mul_pd(r, y2), _mm_set1_pd(c));
    }
    Stereo(_mm_add_pd(_mm_mul_pd(r, y), _mm_cvtepi32_pd(exponent)))
}

#[target_feature(enable = "sse4.1")]
pub unsafe fn sin(x: Stereo) -> Stereo {
    let pi = _mm_set1_pd(3.1415926535846666);
    let tau = _mm_set1_pd(6.2831853071693331);
    let mp = _mm_sub_pd(x.0, _mm_mul_pd(_mm_floor_pd(_mm_div_pd(x.0, tau)), tau));
    let p = _mm_blendv_pd(mp, _mm_sub_pd(mp, tau), _mm_cmpgt_pd(mp, pi));
    let abs = |v| _mm_andnot_pd(_mm_set1_pd(-0.0), v);
    let y = _mm_add_pd(_mm_mul_pd(_mm_set1_pd(1.2732395447237650), p),
        _mm_mul_pd(_mm_mul_pd(_mm_set1_pd(-0.40528473456652137), p), abs(p)));
    Stereo(_mm_add_pd(_mm_mul_pd(_mm_set1_pd(0.22499990463256836),
        _mm_sub_pd(_mm_mul_pd(y, abs(y)), y)), y))
}

/// State is the two signed-64 product lanes, including high words used by GLITCH swaps.
#[target_feature(enable = "sse4.1")]
pub unsafe fn random(state: &mut [i64; 2]) -> Stereo {
    let s = _mm_loadu_si128(state.as_ptr().cast());
    let multiplier = _mm_set1_epi64x(16007); // bits of 7.908508792981e-320
    let next = _mm_mul_epi32(s, multiplier);
    _mm_storeu_si128(state.as_mut_ptr().cast(), next);
    Stereo(_mm_mul_pd(_mm_cvtepi32_pd(_mm_shuffle_epi32::<0x72>(next)),
        _mm_set1_pd(1.0 / 2147483648.0)))
}

/// Linear sample interpolation, including native one-wrap and next-index behavior.
/// Caller guarantees both index lanes are within one wrap of [0, length).
#[target_feature(enable = "sse4.1")]
pub unsafe fn sample(buffer: *const [f64; 2], length: Stereo, index: Stereo) -> Stereo {
    let zero = _mm_setzero_pd();
    let i = _mm_blendv_pd(index.0, _mm_add_pd(index.0, length.0), _mm_cmplt_pd(index.0, zero));
    let i = _mm_blendv_pd(i, _mm_sub_pd(i, length.0), _mm_cmpge_pd(i, length.0));
    let cur = _mm_floor_pd(i);
    let next = _mm_add_pd(i, _mm_set1_pd(1.0));
    let next = _mm_blendv_pd(next, zero, _mm_cmpge_pd(next, length.0));
    let mut ci = [0i32; 4];
    let mut ni = [0i32; 4];
    _mm_storeu_si128(ci.as_mut_ptr().cast(), _mm_cvtpd_epi32(cur));
    _mm_storeu_si128(ni.as_mut_ptr().cast(), _mm_cvtpd_epi32(next));
    let a = _mm_set_pd((*buffer.offset(ci[1] as isize))[1], (*buffer.offset(ci[0] as isize))[0]);
    let b = _mm_set_pd((*buffer.offset(ni[1] as isize))[1], (*buffer.offset(ni[0] as isize))[0]);
    Stereo(_mm_add_pd(_mm_mul_pd(_mm_sub_pd(b, a), _mm_sub_pd(i, cur)), a))
}

// Pointer-only diagnostic ABI: no dependence on compiler-specific SIMD return ABI.
#[no_mangle]
pub unsafe extern "C" fn eidolon_exp2(input: *const f64, output: *mut f64) {
    exp2(Stereo::load(input)).store(output)
}
#[no_mangle]
pub unsafe extern "C" fn eidolon_log2(input: *const f64, output: *mut f64) {
    log2(Stereo::load(input)).store(output)
}
#[no_mangle]
pub unsafe extern "C" fn eidolon_sin(input: *const f64, output: *mut f64) {
    sin(Stereo::load(input)).store(output)
}
#[no_mangle]
pub unsafe extern "C" fn eidolon_rand(state: *mut [i64; 2], output: *mut f64) {
    random(&mut *state).store(output)
}
#[no_mangle]
pub unsafe extern "C" fn eidolon_sample(buffer: *const [f64; 2], length: *const f64, index: *const f64, output: *mut f64) {
    sample(buffer, Stereo::load(length), Stereo::load(index)).store(output)
}
