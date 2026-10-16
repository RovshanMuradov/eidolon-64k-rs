//! Compatibility-profile GL submission using the recovered source arrays and routes.
use std::{ffi::{c_char, c_void, CStr, CString}, ptr};
use crate::{assets, engine::{Engine, Frame}, physics, windows::*};

macro_rules! gl_functions {
    ($( $field:ident: $name:literal ($($arg:ty),*) -> $ret:ty; )*) => {
        pub struct Gl { $(pub $field: unsafe extern "system" fn($($arg),*) -> $ret,)* }
        impl Gl {
            pub unsafe fn load() -> Result<Self, String> {
                Ok(Self { $($field: {
                    let p = wglGetProcAddress(concat!($name, "\0").as_ptr().cast());
                    if (p as usize) <= 3 || p as usize == usize::MAX {
                        return Err(format!("missing OpenGL entrypoint {}", $name));
                    }
                    std::mem::transmute::<*const c_void, unsafe extern "system" fn($($arg),*) -> $ret>(p)
                },)* })
            }
        }
    }
}
gl_functions! {
    create_program: "glCreateShaderProgramv" (u32, i32, *const *const c_char) -> u32;
    get_program: "glGetProgramiv" (u32, u32, *mut i32) -> ();
    program_log: "glGetProgramInfoLog" (u32, i32, *mut i32, *mut c_char) -> ();
    delete_program: "glDeleteProgram" (u32) -> ();
    use_program: "glUseProgram" (u32) -> ();
    uniform_location: "glGetUniformLocation" (u32, *const c_char) -> i32;
    uniform1i: "glUniform1i" (i32, i32) -> ();
    uniform3f: "glUniform3f" (i32, f32, f32, f32) -> ();
    uniform4f: "glUniform4f" (i32, f32, f32, f32, f32) -> ();
    uniform1fv: "glUniform1fv" (i32, i32, *const f32) -> ();
    uniform2fv: "glUniform2fv" (i32, i32, *const f32) -> ();
    uniform3fv: "glUniform3fv" (i32, i32, *const f32) -> ();
    uniform4fv: "glUniform4fv" (i32, i32, *const f32) -> ();
    gen_framebuffers: "glGenFramebuffers" (i32, *mut u32) -> ();
    delete_framebuffers: "glDeleteFramebuffers" (i32, *const u32) -> ();
    bind_framebuffer: "glBindFramebuffer" (u32, u32) -> ();
    framebuffer_texture: "glFramebufferTexture2D" (u32, u32, u32, u32, i32) -> ();
    check_framebuffer: "glCheckFramebufferStatus" (u32) -> u32;
    draw_buffers: "glDrawBuffers" (i32, *const u32) -> ();
    active_texture: "glActiveTexture" (u32) -> ();
    image3d: "glTexImage3D" (u32, i32, i32, i32, i32, i32, i32, u32, u32, *const c_void) -> ();
}

pub struct Graphics {
    pub gl: Gl,
    programs: [u32; 30],
    loader: u32,
    fbos: [u32; 13],
    textures: [u32; 15],
    volume: u32,
    pub dimensions: [u32; 2],
    progress: f32,
}

impl Graphics {
    pub unsafe fn new(dimensions: [u32; 2]) -> Result<Self, String> {
        let mut result = Self { gl: Gl::load()?, programs: [0; 30], loader: 0,
            fbos: [0; 13], textures: [0; 15], volume: 0, dimensions, progress: 0.0 };
        result.loader = result.compile(&[assets::LOADING_SOURCE])?;
        for (name, value) in [("vendor", 0x1f00), ("renderer", 0x1f01), ("version", 0x1f02)] {
            let p = glGetString(value);
            if !p.is_null() { eprintln!("GL {name}: {}", CStr::from_ptr(p.cast()).to_string_lossy()); }
        }
        Ok(result)
    }

    unsafe fn compile(&self, sources: &[&str]) -> Result<u32, String> {
        let pointers: Vec<*const c_char> = sources.iter().map(|s| s.as_ptr().cast()).collect();
        let id = (self.gl.create_program)(0x8b30, pointers.len() as i32, pointers.as_ptr());
        let mut status = 0;
        (self.gl.get_program)(id, 0x8b82, &mut status);
        if status == 0 {
            let mut len = 0;
            (self.gl.get_program)(id, 0x8b84, &mut len);
            let mut log = vec![0_u8; (len.max(1)) as usize];
            (self.gl.program_log)(id, log.len() as i32, ptr::null_mut(), log.as_mut_ptr().cast());
            (self.gl.delete_program)(id);
            return Err(format!("fragment program link failed: {}", String::from_utf8_lossy(&log)));
        }
        Ok(id)
    }

    unsafe fn location(&self, program: u32, name: &str) -> i32 {
        let name = CString::new(name).unwrap();
        (self.gl.uniform_location)(program, name.as_ptr())
    }

    pub unsafe fn loading(&self, dc: Handle, engine: &mut Engine) -> Result<(), String> {
        (self.gl.bind_framebuffer)(0x8d40, 0);
        (self.gl.use_program)(self.loader);
        glViewport(0, 0, self.dimensions[0] as i32, self.dimensions[1] as i32);
        (self.gl.uniform4f)(self.location(self.loader, "u"), self.progress,
            self.dimensions[0] as f32, self.dimensions[1] as f32, 0.0);
        glRecti(-1, -1, 1, 1);
        engine.loading_draw();
        if SwapBuffers(dc) == 0 { return Err("loading SwapBuffers failed".into()); }
        Ok(())
    }

    pub unsafe fn build(&mut self, dc: Handle, engine: &mut Engine,
        mut checkpoint: impl FnMut() -> Result<(), String>) -> Result<(), String> {
        for (index, sources) in assets::PROGRAM_SOURCES.iter().enumerate() {
            checkpoint()?;
            self.programs[index] = self.compile(sources)?;
            self.progress += 0.025_f32;
            self.loading(dc, engine)?;
        }
        (self.gl.gen_framebuffers)(13, self.fbos.as_mut_ptr());
        glGenTextures(15, self.textures.as_mut_ptr());
        let mut texture = 0;
        for index in 0..13 {
            checkpoint()?;
            let fbo = assets::framebuffer(index);
            let [width, height] = fbo.dimensions(self.dimensions);
            (self.gl.bind_framebuffer)(0x8d40, self.fbos[index]);
            for attachment in 0..fbo.attachments {
                glBindTexture(0xde1, self.textures[texture]);
                glTexImage2D(0xde1, 0, 0x8814, width as i32, height as i32, 0, 0x1908, 0x1406, ptr::null());
                glTexParameteri(0xde1, 0x2801, 0x2601);
                glTexParameteri(0xde1, 0x2800, 0x2601);
                if !fbo.initialization_only {
                    glTexParameteri(0xde1, 0x2802, 0x2900); // native GL_CLAMP, not CLAMP_TO_EDGE
                    glTexParameteri(0xde1, 0x2803, 0x2900);
                }
                (self.gl.framebuffer_texture)(0x8d40, 0x8ce0 + attachment as u32, 0xde1, self.textures[texture], 0);
                texture += 1;
            }
            let status = (self.gl.check_framebuffer)(0x8d40);
            if status != 0x8cd5 { return Err(format!("FBO {index} incomplete: {status:#x}")); }
        }
        self.progress += 0.025_f32;
        self.loading(dc, engine)?;
        let frame = engine.evaluate(0, true).unwrap();
        self.draw(engine, &frame, true)?;
        self.progress += 0.025_f32;
        self.loading(dc, engine)?;
        // Exact linear atlas readback: (x+128*y,z) -> 128^3 RGBA float, no retile.
        let mut volume = vec![0.0_f32; 128 * 128 * 128 * 4];
        glBindTexture(0xde1, self.textures[0]);
        glGetTexImage(0xde1, 0, 0x1908, 0x1406, volume.as_mut_ptr().cast());
        self.progress += 0.025_f32;
        self.loading(dc, engine)?;
        glGenTextures(1, &mut self.volume);
        (self.gl.active_texture)(0x84c0);
        glBindTexture(0x806f, self.volume);
        (self.gl.image3d)(0x806f, 0, 0x8814, 128, 128, 128, 0, 0x1908, 0x1406, volume.as_ptr().cast());
        glTexParameteri(0x806f, 0x2801, 0x2601);
        glTexParameteri(0x806f, 0x2800, 0x2601);
        for wrap in [0x8072, 0x2802, 0x2803] { glTexParameteri(0x806f, wrap, 0x2901); }
        self.progress += 0.025_f32;
        self.loading(dc, engine)?;
        Ok(())
    }

    pub unsafe fn playback_loading(&mut self, dc: Handle, engine: &mut Engine) -> Result<(), String> {
        self.progress += 0.025_f32;
        self.loading(dc, engine)
    }

    pub unsafe fn draw(&self, engine: &mut Engine, frame: &Frame, initialization: bool) -> Result<(), String> {
        for (index, _, setup) in engine.draw_schedule(frame, initialization) {
            if setup {
                let pass = assets::pass(index);
                let program = self.programs[pass.program];
                (self.gl.use_program)(program);
                (self.gl.bind_framebuffer)(0x8d40, pass.framebuffer.map(|f| self.fbos[f]).unwrap_or(0));
                let [width, height] = if let Some(index) = pass.framebuffer {
                    let fbo = assets::framebuffer(index);
                    (self.gl.draw_buffers)(fbo.attachments as i32, [0x8ce0, 0x8ce1, 0x8ce2].as_ptr());
                    fbo.dimensions(self.dimensions)
                } else { self.dimensions };
                glViewport(0, 0, width as i32, height as i32);
                (self.gl.uniform3f)(self.location(program, "uTimeResolution"), frame.clock.seconds, width as f32, height as f32);
                (self.gl.uniform1i)(self.location(program, "uClouds"), 0);
                for (input, texture) in pass.inputs.iter().enumerate() {
                    (self.gl.active_texture)(0x84c1 + input as u32);
                    glBindTexture(0xde1, self.textures[*texture]);
                    let base = self.location(program, "sTD2DInputs");
                    (self.gl.uniform1i)(base + input as i32, input as i32 + 1);
                }
                for uniform in &frame.uniforms {
                    let function = match uniform.components { 1 => self.gl.uniform1fv, 2 => self.gl.uniform2fv,
                        3 => self.gl.uniform3fv, _ => self.gl.uniform4fv };
                    function(self.location(program, uniform.name), 1, uniform.value.as_ptr());
                }
                for (record, name) in engine.records.iter().zip(physics::ROTATION_NAMES) {
                    (self.gl.uniform3fv)(self.location(program, name), 1, record.rotation.as_ptr());
                }
            }
            // Deliberately includes skipped-setup initialization draws.
            glRecti(-1, -1, 1, 1);
        }
        // Do not consume/turn native ignored uniform errors into an early endpoint.
        // Independent capture can inspect error state without changing this draw schedule.
        Ok(())
    }
}

impl Drop for Graphics {
    fn drop(&mut self) { unsafe {
        (self.gl.use_program)(0);
        (self.gl.bind_framebuffer)(0x8d40, 0);
        for program in self.programs.into_iter().chain([self.loader]) {
            if program != 0 { (self.gl.delete_program)(program); }
        }
        (self.gl.delete_framebuffers)(13, self.fbos.as_ptr());
        glDeleteTextures(15, self.textures.as_ptr());
        glDeleteTextures(1, &self.volume);
    } }
}
