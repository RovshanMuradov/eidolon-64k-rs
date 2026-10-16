//! Scalar SSE operation order from 0x407c64..0x407f9c.
use crate::assets::{self, Curve, Row, Track};
use crate::contract::Clock;

pub fn select(clock: Clock) -> Option<Row> {
    (0..assets::ROW_COUNT).map(assets::row).find(|row| clock.beat < row.end)
}

pub fn evaluate(curve: Curve, time: f32) -> f32 {
    assert!(curve.words >= 4 && curve.words.is_multiple_of(4));
    let key = |i| assets::curve_word(curve.offset + i);
    if curve.words == 4 || time <= key(1) {
        return key(2);
    }
    let mut j = 4;
    while j < curve.words - 4 && time > key(j + 1) {
        j += 4;
    }
    // Earliest segment wins at equal timestamps; do not deduplicate keys.
    let end = key(j + 1);
    let t = (time.min(end) - key(j - 3)) / (end - key(j - 3));
    let delta = key(j + 2) - key(j - 2);
    let m0 = key(j - 1);
    let m1 = key(j);
    let a = ((((delta + delta) + delta) - m0) - m0) - m1;
    let b = ((m1 + m0) - delta) - delta;
    (((((b * t) + a) * t) + m0) * t) + key(j - 2)
}

pub fn evaluate_track(track: Track, local_beat: f32) -> [f32; 4] {
    let mut values = [0.0; 4];
    for (value, curve) in values.iter_mut().zip(track.curves).take(track.components) {
        *value = evaluate(curve, local_beat);
    }
    values
}
