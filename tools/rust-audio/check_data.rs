#[path = "../../src/audio/mod.rs"]
mod audio;
use std::io::{self, Write};

fn main() {
    let score = audio::score::Score::decode(audio::data::SCORE).unwrap();
    assert_eq!(score.bpm.to_bits(), 80.0f32.to_bits());
    assert_eq!(score.frames, audio::TOTAL_FRAMES);
    assert_eq!(score.quantum, audio::EVENT_QUANTUM);
    // Malformed/truncated sources must fail rather than produce a partial schedule.
    assert!(audio::score::Score::decode(&audio::data::SCORE[..100]).is_err());
    let mut invalid = audio::data::SCORE.to_vec();
    *invalid.last_mut().unwrap() ^= 1;
    assert!(audio::score::Score::decode(&invalid).is_err());
    let mut output = io::BufWriter::new(io::stdout().lock());
    for e in &score.events {
        output.write_all(&e.frame.to_le_bytes()).unwrap();
        output.write_all(&[e.channel, e.kind, e.special, e.value, e.velocity]).unwrap();
    }
    let mut scheduler = audio::score::Scheduler::fixed().unwrap();
    let mut emitted = Vec::new();
    for frame in (0..score.frames).step_by(score.quantum as usize) {
        scheduler.dispatch(frame, |e| emitted.push(e.clone()));
    }
    assert_eq!(emitted, score.events);
    for &(id, samples) in audio::data::WAVES {
        let wave = audio::data::wave(id).unwrap();
        assert_eq!(wave.len(), samples.len() * 2);
    }
    assert!(audio::data::wave(65535).is_none());
    assert!(audio::render(&mut []).is_err());
}
