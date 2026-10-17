use crate::{assets, contract::{Clock, CONTROLLED_STEP, PRESENTED_FRAMES}, engine::Engine, fp::{self, GraphicsFp}, physics, timeline};

#[test]
fn x87_helpers_and_native_fp_scope() {
    let _fp = GraphicsFp::enter();
    assert_eq!(fp::sqrt(4.0), 2.0);
    assert_eq!(fp::atan2(0.0, 1.0).to_bits(), 0);
    assert_eq!(fp::atan2(1.0, 0.0), std::f32::consts::FRAC_PI_2);
    assert_eq!(fp::acos(1.0).to_bits(), 0);
    assert_eq!(fp::acos(0.0), std::f32::consts::FRAC_PI_2);
    assert_eq!(fp::acos(-1.0), std::f32::consts::PI);
}

#[test]
fn duplicate_key_and_exit_boundaries() {
    let curve = assets::Curve { offset: 690, words: 112 };
    assert_eq!(timeline::evaluate(curve, 5.0).to_bits(), assets::curve_word(690 + 14 * 4 + 2).to_bits());
    assert!(timeline::evaluate(curve, f32::from_bits(5.0_f32.to_bits() + 1)) < 0.000001);
    assert_eq!(timeline::select(Clock::from_samples(735 * 1439)).unwrap().index, 0);
    assert_eq!(timeline::select(Clock::from_samples(735 * 1440)).unwrap().index, 1);
    assert_eq!(timeline::select(Clock::from_samples(735 * 26999)).unwrap().index, 49);
    assert!(timeline::select(Clock::from_samples(735 * 27000)).is_none());
}

#[test]
fn zero_dt_and_strict_reset_distance() {
    let _fp = GraphicsFp::enter();
    let initial = physics::initial_records()[0];
    let mut record = initial;
    let mut target = [10.0, 20.0, 30.0, 0.0];
    let before = target;
    record.update(-0.0, &mut target, [0.0; 4]);
    assert_eq!(record.words(), initial.words());
    assert_eq!(target, before);
    let mut target = [5.0, 0.0, 0.0, 0.0];
    record.update(0.1, &mut target, [5.0, 0.0, 0.0, 0.0]);
    assert!(target[0] < 1.0); // exactly distance 5 must spring, not snap/reset.
    record = initial;
    let mut target = [6.0, 0.0, 0.0, 0.0];
    record.update(0.1, &mut target, [6.0, 0.0, 0.0, 0.0]);
    assert_eq!(target[0], 6.0); // reset with stationary lookahead, error retained as zero.
    assert_eq!(record.velocity, [0.0; 4]);
}

#[test]
fn complete_state_schedule_retains_program_values_and_unused_record() {
    let _fp = GraphicsFp::enter();
    let mut engine = Engine::default();
    let unused = engine.records[3].words();
    let initial = engine.evaluate(0, true).unwrap();
    assert_eq!(engine.records[0].words(), physics::initial_records()[0].words());
    let initialization = engine.draw_schedule(&initial, true);
    assert!(initialization[..18].iter().all(|(_, _, setup)| *setup));
    assert_eq!(initialization[18], (18, 17, false));
    engine.loading_draw();
    let mut retained_position = None;
    for n in 0..PRESENTED_FRAMES {
        let frame = engine.evaluate(n * CONTROLLED_STEP, true).unwrap();
        for uniform in &frame.uniforms {
            assert!(uniform.value[..uniform.components].iter().all(|v| v.is_finite()), "frame {n} {}", uniform.name);
        }
        let schedule = engine.draw_schedule(&frame, false);
        assert_eq!(schedule.len(), 19);
        let previous = if n == 0 { crate::engine::LOADING_PASS } else { 18 };
        assert!(schedule[..9].iter().all(|(_, active, setup)| *active == previous && !setup));
        assert!(schedule[9..].iter().all(|(requested, active, setup)| requested == active && *setup));
        if frame.row.index == 11 {
            retained_position = Some(engine.program_uniforms[21]["uMainCharacterPos"].value.map(f32::to_bits));
        }
        if frame.row.index == 43 {
            assert_eq!(Some(engine.program_uniforms[21]["uMainCharacterPos"].value.map(f32::to_bits)), retained_position);
        }
    }
    assert_eq!(engine.records[3].words(), unused);
}
