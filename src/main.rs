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
    if mode == "--raw-stream" || mode == "--state-stream" {
        let mut out = io::BufWriter::new(io::stdout().lock());
        out.write_all(if mode == "--raw-stream" { b"EIDRAW01" } else { b"EIDSTA01" })?;
        let mut engine = Engine::default();
        let initialization = engine.evaluate(0, true).unwrap();
        engine.draw_schedule(&initialization, true);
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
        println!("Eidolon CPU engine candidate; audiovisual runtime pending");
        println!("rows={} programs={} source_array_bytes={} loading_bytes={} pcm_bytes={}",
            assets::ROW_COUNT, assets::PROGRAM_COUNT, shader_bytes, assets::LOADING_SOURCE.len() - 1, contract::PCM_BYTES);
        println!("--raw-stream / --state-stream: binary controlled-clock diagnostics");
    }
    Ok(())
}
