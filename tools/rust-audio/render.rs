#[path="../../src/audio/mod.rs"]
mod audio;
use std::{fs::File,io::{BufWriter,Write}};

fn main() {
    let args:Vec<_>=std::env::args().collect();
    let frames:usize=args[2].parse().unwrap();
    let mut pcm=vec![f32::from_bits(0x7fc01234);frames*2];
    if frames==audio::TOTAL_FRAMES as usize {
        audio::render(&mut pcm).expect("standalone synthesis");
    } else {
        eprintln!("{:?}",audio::runtime::render_prefix(&mut pcm).expect("standalone prefix"));
    }
    assert!(pcm.iter().all(|x|x.to_bits()!=0x7fc01234),"unwritten PCM");
    let mut file=BufWriter::new(File::create(&args[1]).unwrap());
    for frame in pcm.chunks_exact(2) {
        file.write_all(&frame[0].to_le_bytes()).unwrap();
        file.write_all(&frame[1].to_le_bytes()).unwrap();
    }
    file.flush().unwrap();
    println!("RUST_RENDERED frames={frames} standalone=true");
}
