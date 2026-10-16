//! Independent Linux-only full-production-entrypoint probe; no prefix/oracle path.
#[path="../../../src/audio/mod.rs"] mod audio;
use std::{fs::File, io::{BufWriter, Write}};

#[repr(C)] struct Filter { code: u16, jt: u8, jf: u8, k: u32 }
#[repr(C)] struct Program { len: u16, filter: *const Filter }
unsafe extern "C" { fn prctl(option: i32, ...) -> i32; }

fn close_file_inputs() {
    // x86_64 Linux seccomp: prohibit opening files or replacing the process after
    // the output descriptor is opened. Existing libc/runtime mappings are retained.
    assert!(cfg!(all(target_os="linux", target_arch="x86_64")));
    let mut rules = vec![Filter {code:0x20,jt:0,jf:0,k:4},
        Filter {code:0x15,jt:1,jf:0,k:0xc000003e},
        Filter {code:0x06,jt:0,jf:0,k:0x80000000},
        Filter {code:0x20,jt:0,jf:0,k:0}];
    // open, creat, openat, openat2, execve, execveat; also reject x32 syscall ABI.
    rules.push(Filter {code:0x35,jt:0,jf:1,k:0x40000000});
    rules.push(Filter {code:0x06,jt:0,jf:0,k:0x00050001});
    for number in [2,85,257,437,59,322] {
        rules.push(Filter {code:0x15,jt:0,jf:1,k:number});
        rules.push(Filter {code:0x06,jt:0,jf:0,k:0x00050001});
    }
    rules.push(Filter {code:0x06,jt:0,jf:0,k:0x7fff0000});
    let program = Program {len:rules.len() as u16,filter:rules.as_ptr()};
    unsafe {
        assert_eq!(prctl(38,1usize,0usize,0usize,0usize),0,"no_new_privs");
        assert_eq!(prctl(22,2usize,&program as *const Program),0,"seccomp");
    }
    assert_eq!(File::open("/etc/passwd").unwrap_err().raw_os_error(),Some(1));
}

fn dump_assets(path: &str) {
    let mut out = BufWriter::new(File::create(path).unwrap());
    out.write_all(b"EIDAUD01").unwrap();
    for raw in [audio::data::SCORE,audio::data::PATCH] {
        out.write_all(&(raw.len() as u32).to_le_bytes()).unwrap(); out.write_all(raw).unwrap();
    }
    out.write_all(&(audio::data::WAVES.len() as u32).to_le_bytes()).unwrap();
    for &(id, wave) in audio::data::WAVES {
        out.write_all(&(id as u32).to_le_bytes()).unwrap();
        out.write_all(&(wave.len() as u32).to_le_bytes()).unwrap();
        for sample in wave { out.write_all(&sample.to_le_bytes()).unwrap(); }
    }
    for value in audio::formants::COEFFICIENTS { out.write_all(&value.to_le_bytes()).unwrap(); }
    out.flush().unwrap();
}

#[allow(deprecated)]
fn main() {
    let args: Vec<_> = std::env::args().collect();
    if args[1] == "--assets" { dump_assets(&args[2]); return; }
    assert_eq!(args[1],"--render");
    let output = File::create(&args[2]).unwrap();
    let mut short = vec![f32::from_bits(0x7fc01234);128];
    assert!(audio::render(&mut short).is_err());
    assert!(short.iter().all(|x|x.to_bits()==0x7fc01234));
    let mut pcm = vec![f32::from_bits(0x7fc01234);39_929_088];
    close_file_inputs();
    let before = unsafe { core::arch::x86_64::_mm_getcsr() };
    audio::render(&mut pcm).expect("production render");
    assert_eq!(unsafe { core::arch::x86_64::_mm_getcsr() },before,"caller MXCSR");
    assert!(pcm.iter().all(|x|x.to_bits()!=0x7fc01234),"incomplete output");
    let mut out = BufWriter::new(output);
    for block in pcm.chunks(16384) {
        let mut bytes=Vec::with_capacity(block.len()*4);
        for value in block { bytes.extend(value.to_le_bytes()); }
        out.write_all(&bytes).unwrap();
    }
    out.flush().unwrap();
    println!("FULL_RENDER frames=19964544 bytes=159716352 file_inputs_denied=true mxcsr_restored=true poison_remaining=0");
}
