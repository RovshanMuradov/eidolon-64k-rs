//! CPU candidate probe. This executable does not yet start the audiovisual runtime.
use std::io::{self, Write};
use eidolon::{assets, contract, engine::Engine, fp::GraphicsFp};

fn write_words(out: &mut impl Write, words: impl IntoIterator<Item = u32>) -> io::Result<()> {
    for word in words { out.write_all(&word.to_le_bytes())?; }
    Ok(())
}

fn main() -> io::Result<()> {
    let _fp = GraphicsFp::enter();
    let mode = std::env::args().nth(1).unwrap_or_default();
    if mode == "--render-pcm" {
        let path = std::env::args().nth(2).ok_or_else(|| io::Error::other("--render-pcm requires an output path"))?;
        let worker = eidolon::synthesis::spawn(eidolon::audio::render).map_err(io::Error::other)?;
        let pcm = worker.join().map_err(|_| io::Error::other("synthesis worker panicked"))?
            .map_err(io::Error::other)?;
        // Both supported x86 targets are little-endian; every float was initialized before exposure.
        let bytes = unsafe { std::slice::from_raw_parts(pcm.as_ptr().cast::<u8>(), contract::PCM_BYTES) };
        std::fs::File::create(path)?.write_all(bytes)?;
        println!("INTEGRATED_RUST_PCM frames={} bytes={} standalone=true", contract::PCM_FRAMES, bytes.len());
    } else if mode == "--shader-stream" {
        let mut out = io::BufWriter::new(io::stdout().lock());
        out.write_all(b"EIDGLS01")?;
        // Preserve source-array boundaries and terminating NULs for glCreateShaderProgramv.
        write_words(&mut out, [assets::PROGRAM_COUNT as u32 + 1])?;
        for program in assets::PROGRAM_SOURCES.iter().copied().chain([&[assets::LOADING_SOURCE][..]]) {
            write_words(&mut out, [program.len() as u32])?;
            for source in program {
                write_words(&mut out, [source.len() as u32])?;
                out.write_all(source.as_bytes())?;
            }
        }
        out.flush()?;
    } else if mode == "--raw-stream" || mode == "--state-stream" {
        let mut out = io::BufWriter::new(io::stdout().lock());
        out.write_all(if mode == "--raw-stream" { b"EIDRAW01" } else { b"EIDSTA01" })?;
        let mut engine = Engine::default();
        let initialization = engine.evaluate(0, true).unwrap();
        engine.draw_schedule(&initialization, true);
        engine.loading_draw();
        for n in 0..contract::PRESENTED_FRAMES {
            let frame = engine.evaluate(n * contract::CONTROLLED_STEP, mode == "--state-stream").unwrap();
            write_words(&mut out, [n, frame.clock.cursor, frame.clock.seconds.to_bits(), frame.clock.beat.to_bits(),
                frame.row.index as u32, frame.local_beat.to_bits(), frame.dt.to_bits(), frame.uniforms.len() as u32])?;
            for uniform in &frame.uniforms {
                write_words(&mut out, [uniform.name_index, uniform.components as u32])?;
                write_words(&mut out, uniform.value[..uniform.components].iter().map(|v| v.to_bits()))?;
            }
            if mode == "--state-stream" {
                for record in engine.records { write_words(&mut out, record.words())?; }
                engine.draw_schedule(&frame, false);
            }
        }
        assert!(engine.evaluate(contract::PRESENTED_FRAMES * contract::CONTROLLED_STEP, false).is_none());
        out.flush()?;
    } else {
        let shader_bytes: usize = assets::PROGRAM_SOURCES.iter().flat_map(|p| p.iter()).map(|s| s.len() - 1).sum();
        println!("Eidolon CPU engine probe; WGL/waveOut candidate is eidolon-runtime");
        println!("rows={} programs={} source_array_bytes={} loading_bytes={} pcm_bytes={}",
            assets::ROW_COUNT, assets::PROGRAM_COUNT, shader_bytes, assets::LOADING_SOURCE.len() - 1, contract::PCM_BYTES);
        println!("--raw-stream / --state-stream: binary controlled-clock diagnostics");
        println!("--shader-stream: exact effective NUL-terminated shader source arrays");
        println!("--render-pcm PATH: full standalone synthesis using the production worker seam");
    }
    Ok(())
}
