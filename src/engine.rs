//! Stateful CPU evaluation and native draw schedule, independent of a GL context.
use std::collections::BTreeMap;
use crate::{assets::{self, Row}, contract::Clock, physics::{self, Record}, timeline};

#[derive(Clone, Copy, Debug)]
pub struct Uniform {
    pub name_index: u32,
    pub name: &'static str,
    pub components: usize,
    pub value: [f32; 4],
}

#[derive(Debug)]
pub struct Frame {
    pub clock: Clock,
    pub row: Row,
    pub local_beat: f32,
    pub dt: f32,
    pub uniforms: Vec<Uniform>,
}

pub struct Engine {
    pub records: [Record; 4],
    pub previous_seconds: f32,
    /// Only values actually uploaded by this CPU model; GLSL defaults remain driver-owned.
    pub program_uniforms: [BTreeMap<&'static str, Uniform>; assets::PROGRAM_COUNT],
    pub active_pass: Option<usize>,
}

impl Default for Engine {
    fn default() -> Self {
        Self { records: physics::initial_records(), previous_seconds: 0.0,
            program_uniforms: std::array::from_fn(|_| BTreeMap::new()), active_pass: None }
    }
}

impl Engine {
    /// Raw tracks or physics-updated tracks in descriptor order. No row-triggered state reset.
    pub fn evaluate(&mut self, cursor: u32, apply_physics: bool) -> Option<Frame> {
        let clock = Clock::from_samples(cursor);
        let row = timeline::select(clock)?;
        let local_beat = clock.beat - row.start;
        let dt = clock.seconds - self.previous_seconds;
        let uniforms = row.tracks().map(|track| {
            let mut value = timeline::evaluate_track(track, local_beat);
            let name = track.name();
            if apply_physics && let Some(index) = physics::POSITION_NAMES.iter().position(|n| *n == name) {
                let lookahead = timeline::evaluate_track(track, local_beat + 0.01_f32);
                self.records[index].update(dt, &mut value, lookahead);
            }
            Uniform { name_index: track.name_index, name, components: track.components, value }
        }).collect();
        self.previous_seconds = clock.seconds;
        Some(Frame { clock, row, local_beat, dt, uniforms })
    }

    /// Initialization-only timeline passes skip setup but still issue glRecti.
    /// Each returned item is (requested pass, actually active pass, setup performed).
    pub fn draw_schedule(&mut self, frame: &Frame, initialization: bool) -> Vec<(usize, usize, bool)> {
        frame.row.passes().map(|index| {
            let pass = assets::pass(index);
            let skip = !initialization && pass.framebuffer
                .is_some_and(|fbo| assets::framebuffer(fbo).initialization_only);
            if !skip {
                self.active_pass = Some(index);
                let state = &mut self.program_uniforms[pass.program];
                for uniform in &frame.uniforms { state.insert(uniform.name, *uniform); }
                for (index, record) in self.records.iter().enumerate() {
                    let mut value = [0.0; 4];
                    value[..3].copy_from_slice(&record.rotation);
                    let name = physics::ROTATION_NAMES[index];
                    state.insert(name, Uniform { name_index: u32::MAX, name, components: 3, value });
                }
            }
            (index, self.active_pass.expect("initialization must precede timeline draws"), !skip)
        }).collect()
    }
}
