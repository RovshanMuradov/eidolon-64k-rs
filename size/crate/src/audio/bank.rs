//! Native ordered data-chunk bank scan, pinned to the accepted Windows gm.dls.
use super::alloc::{vec,vec::Vec};

pub const BYTES: usize = 3_440_660;
pub const SHA256: [u8;32] = [0x32,0x29,0xb0,0x9b,0x9d,0x7d,0x9f,0x3f,0x47,0x93,0xb0,0xd9,0xb3,0x4f,0xe6,0xab,0xc7,0x5c,0xfa,0x4a,0x25,0x03,0xc0,0xc9,0x0f,0x43,0xff,0x65,0x1b,0xa7,0xf2,0xc0];

// T26 owns the Windows system-directory implementation; the CPU harness injects
// the immutable bank through the same ABI. Neither path supplies recorded music.
extern "C" { fn eidolon_read_gm_dls(dst:*mut u8,capacity:u32)->u32; }

/// FNV-1a over the whole bank: identity pin of the accepted 3440660-byte gm.dls
/// (full SHA-256 3229b09b…f2c0 recorded in artifacts/optimization/audio/assets.json).
pub const FNV1A: u32 = 0xbb87d9a5;
pub fn digest(data:&[u8])->u32 {
    data.iter().fold(2166136261u32,|h,&b| (h^b as u32).wrapping_mul(16777619))
}

pub struct Bank {
    pub samples:Vec<[f64;2]>,
    pub starts:[u32;16],
}

pub fn decode(data:&[u8])->Result<Bank,&'static str> {
    if data.len()!=BYTES || digest(data)!=FNV1A { return Err("gm.dls"); }
    // Identity-pinned bank: the chunk walk below cannot fail and writes all 85548 pairs.
    let mut samples=Vec::<[f64;2]>::with_capacity(85548);
    let mut starts=[0u32;16];
    unsafe {
        samples.set_len(85548);
        let base=samples.as_mut_ptr(); let mut out=base;
        let mut p=data.as_ptr(); let end=p.add(data.len()-8);
        let (mut id,mut found)=(0u16,0usize);
        while p<end {
            if p.cast::<u32>().read_unaligned()==u32::from_le_bytes(*b"data") {
                let size=p.add(4).cast::<u32>().read_unaligned() as usize;
                if found<15 && *super::data::WAVE_IDS.as_ptr().add(found)==id {
                    starts[found]=out.offset_from(base) as u32;
                    let mut q=p.add(8);
                    for _ in 0..size/2 {
                        let s=q.cast::<i16>().read_unaligned() as f64/32768.0;
                        *out=[s,s]; *out.add(1)=[s,s]; out=out.add(2); q=q.add(2);
                    }
                    found+=1;
                }
                id+=1; p=p.add(8+size);
            }
            p=p.add(1);
        }
        starts[15]=out.offset_from(base) as u32;
    }
    Ok(Bank{samples,starts})
}

pub fn load()->Result<Bank,&'static str> {
    // Extra byte makes a longer, otherwise matching-prefix bank fail identity validation.
    let mut data=vec![0;BYTES+1];
    let size=unsafe { eidolon_read_gm_dls(data.as_mut_ptr(),data.len() as u32) };
    decode(&data[..size as usize])
}
