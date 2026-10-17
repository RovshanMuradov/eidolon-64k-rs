//! Instruction-ordered translation of 0x406019..0x4062d0; see docs/en/04-physics.md.
use crate::fp;

pub const POSITION_NAMES: [&str; 4] = [
    "uMainCharacterPos", "uEvilCharacterPos1", "uEvilCharacterPos2", "uEvilCharacterPos3",
];
pub const ROTATION_NAMES: [&str; 4] = [
    "uMainCharacterRotation", "uEvilCharacterRotation1", "uEvilCharacterRotation2", "uEvilCharacterRotation3",
];

#[repr(C)]
#[derive(Clone, Copy, Debug)]
pub struct Record {
    /// SIMD lane order: [0, z, y, x].
    pub position: [f32; 4],
    pub velocity: [f32; 4],
    /// spin divisor, stiffness, damping, bank gain.
    pub parameters: [f32; 4],
    pub rotation: [f32; 3],
    pub unused: f32,
}

const _: () = assert!(size_of::<Record>() == 64);

pub fn initial_records() -> [Record; 4] {
    [[0.25, 3.5, 2.0, 320.0], [1.0, 1.5, 2.0, 400.0],
     [1.0, 2.5, 1.0, 400.0], [1.0, 1.5, 1.0, 400.0]].map(|parameters| Record {
        position: [0.0; 4], velocity: [0.0; 4], parameters, rotation: [0.0; 3], unused: 0.0,
    })
}

fn squared_length(v: [f32; 4]) -> f32 {
    ((v[3] * v[3]) + (v[2] * v[2])) + (v[1] * v[1])
}

impl Record {
    /// Caller holds GraphicsFp on this thread. Zero dt leaves target and record untouched.
    pub fn update(&mut self, dt: f32, target: &mut [f32; 4], lookahead: [f32; 4]) {
        if dt == 0.0 { return; }
        let t = [0.0, target[2], target[1], target[0]];
        let l = [0.0, lookahead[2], lookahead[1], lookahead[0]];
        let mut error = std::array::from_fn(|i| t[i] - self.position[i]);
        let [spin_divisor, stiffness, damping, bank_gain] = self.parameters;
        if squared_length(error) > 25.0 {
            error = [0.0; 4];
            let ratio = damping / stiffness;
            for i in 0..4 {
                self.velocity[i] = (l[i] - t[i]) / 0.01_f32;
                self.position[i] = t[i] - (ratio * self.velocity[i]);
            }
        }
        let old_velocity = self.velocity;
        let d = damping * dt;
        let s = stiffness * dt;
        for (i, error) in error.into_iter().enumerate() {
            let decay = d * self.velocity[i];
            let damped = self.velocity[i] - decay;
            let spring = s * error;
            self.velocity[i] = damped + spring;
            let step = dt * self.velocity[i];
            self.position[i] = step + self.position[i];
        }
        let speed = fp::sqrt(squared_length(self.velocity));
        let spin_increment = (speed / spin_divisor) * dt;
        self.rotation[1] = fp::atan2(self.velocity[3], self.velocity[1]);
        self.rotation[2] = 0.0;
        let old_speed = fp::sqrt(squared_length(old_velocity));
        if speed != 0.0 && old_speed != 0.0 {
            let cross = (self.velocity[3] * old_velocity[1]) - (self.velocity[1] * old_velocity[3]);
            let sign = if cross < 0.0 { -1.0 } else { 1.0 };
            let products: [f32; 4] = std::array::from_fn(|i|
                (self.velocity[i] / speed) * (old_velocity[i] / old_speed));
            let mut cosine = (products[3] + products[2]) + products[1];
            // Ordered comparisons preserve native NaN behavior.
            if cosine > 1.0 { cosine = 1.0; }
            if cosine < -1.0 { cosine = -1.0; }
            let angle = fp::acos(cosine);
            self.rotation[2] = ((((angle * sign) * speed) * bank_gain) / dt) * 0.001_f32;
        }
        self.rotation[0] += spin_increment;
        target[..3].copy_from_slice(&[self.position[3], self.position[2], self.position[1]]);
    }

    pub fn words(self) -> [u32; 16] {
        let mut words = [0; 16];
        for (dst, value) in words.iter_mut().zip(self.position.into_iter()
            .chain(self.velocity).chain(self.parameters).chain(self.rotation).chain([self.unused])) {
            *dst = value.to_bits();
        }
        words
    }
}
