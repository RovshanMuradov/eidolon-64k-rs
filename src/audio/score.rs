//! Synth.cpp delta decoding and ProcessStream ordering, independent of graph dispatch.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Event {
    pub frame: u32,
    pub channel: u8,
    pub kind: u8,
    pub special: u8,
    pub value: u8,
    pub velocity: u8,
}

pub struct Score {
    pub bpm: f32,
    pub frames: u32,
    pub quantum: u32,
    pub events: Vec<Event>,
}

fn word(data: &[u8], at: usize) -> Result<u32, &'static str> {
    Ok(u32::from_le_bytes(data.get(at..at + 4).ok_or("truncated score")?.try_into().unwrap()))
}

impl Score {
    pub fn decode(encoded: &[u8]) -> Result<Self, &'static str> {
        let bpm = f32::from_bits(word(encoded, 0)?);
        let frames = word(encoded, 4)?;
        let quantum = word(encoded, 8)?;
        if quantum == 0 { return Err("zero event quantum"); }
        let size = word(encoded, 12)? as usize;
        let mut data = encoded.get(16..16 + size).ok_or("truncated delta stream")?.to_vec();
        let mut previous = 0u8;
        for value in &mut data { previous = previous.wrapping_add(*value); *value = previous; }
        // The terminal DWORD is deliberately not delta encoded (native Init).
        if encoded.get(16 + size..) != Some(&[255u8; 4][..]) { return Err("invalid score sentinel"); }
        data.extend_from_slice(&[255; 4]);
        let mut at = 0;
        let mut events = Vec::new();
        loop {
            let info = word(&data, at)?;
            at += 4;
            if info == u32::MAX { break; }
            let n = (info & 0xffff) as usize;
            let kind = ((info >> 24) & 15) as u8;
            if ![0, 1, 3].contains(&kind) { return Err("unsupported fixed-score stream"); }
            let stride = if kind == 1 { 5 } else { 4 };
            let stream = data.get(at..at + n * stride).ok_or("truncated event stream")?;
            for i in 0..n {
                let stamp = u32::from(stream[i]) | (u32::from(stream[n+i]) << 8) | (u32::from(stream[2*n+i]) << 16);
                events.push(Event {
                    frame: stamp.checked_mul(quantum).ok_or("timestamp overflow")?,
                    channel: (info >> 28) as u8, kind,
                    special: (info >> 16) as u8,
                    value: stream[3*n+i],
                    // Native note-off also reads the adjacent decoded bytes.
                    velocity: if kind != 3 { *data.get(at+4*n+i).ok_or("missing velocity")? } else { 0 },
                });
            }
            at += n * stride;
        }
        if at != data.len() { return Err("trailing score bytes"); }
        // Stable sort preserves stream order for simultaneous events.
        events.sort_by_key(|e| e.frame);
        Ok(Self { bpm, frames, quantum, events })
    }
}

/// Event cursor preserves ProcessStream order without scanning inactive streams.
pub struct Scheduler { pub score: Score, next: usize }
impl Scheduler {
    pub fn fixed() -> Result<Self, &'static str> {
        Ok(Self { score: Score::decode(super::data::SCORE)?, next: 0 })
    }
    pub fn dispatch(&mut self, timestamp: u32, mut emit: impl FnMut(&Event)) {
        while let Some(event) = self.score.events.get(self.next) {
            if event.frame > timestamp { break; }
            emit(event);
            self.next += 1;
        }
    }
}

#[no_mangle]
pub extern "C" fn eidolon_score_new() -> *mut Scheduler {
    match Scheduler::fixed() {
        Ok(s) => Box::into_raw(Box::new(s)),
        Err(_) => core::ptr::null_mut(),
    }
}
#[no_mangle]
pub unsafe extern "C" fn eidolon_score_dispatch(
    state: *mut Scheduler, timestamp: u32,
    emit: extern "C" fn(u32, u32, u32, u32, u32),
) {
    (*state).dispatch(timestamp, |e| emit(e.channel.into(), e.kind.into(), e.special.into(), e.value.into(), e.velocity.into()));
}
#[no_mangle]
pub unsafe extern "C" fn eidolon_score_free(state: *mut Scheduler) { drop(Box::from_raw(state)); }
