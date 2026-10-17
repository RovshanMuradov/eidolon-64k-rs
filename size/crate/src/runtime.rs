//! Windows audiovisual runtime. Synthesis is injected through the shared Rust contract.
//! Graphics-only mode is explicitly diagnostic and never supplies placeholder audio.
use core::ptr;
use alloc::{boxed::Box, vec::Vec};
use crate::RuntimeError as Error;
#[cfg(not(feature = "sizecoded"))]
use alloc::format;
use crate::{contract, engine::Engine, fp::GraphicsFp, graphics::Graphics, observe::{self, RuntimeSnapshot}, synthesis, windows::*};

pub use synthesis::RenderPcm;

unsafe extern "system" fn window_proc(window: Handle, message: u32, wparam: usize, lparam: isize) -> isize {
    if message == 0x10 || message == 0x2 { // WM_CLOSE / WM_DESTROY
        PostQuitMessage(0);
        return 0;
    }
    DefWindowProcA(window, message, wparam, lparam)
}

struct Window { window: Handle, dc: Handle, context: Handle, cursor_hidden: bool }
impl Window {
    unsafe fn new() -> Result<Self, Error> {
        let instance = GetModuleHandleA(ptr::null());
        let class_name = b"EidolonRust\0";
        let class = WindowClass { style: 0x20, procedure: window_proc, class_extra: 0, window_extra: 0,
            instance, icon: ptr::null_mut(), cursor: ptr::null_mut(), background: ptr::null_mut(),
            menu: ptr::null(), name: class_name.as_ptr().cast() };
        if RegisterClassA(&class) == 0 { return Err("class".into()); }
        let window = CreateWindowExA(0, class.name, b"Eidolon\0".as_ptr().cast(), 0x91000000,
            0, 0, 0, 0, ptr::null_mut(), ptr::null_mut(), instance, ptr::null_mut());
        if window.is_null() { return Err("window".into()); }
        let mut result = Self { window, dc: ptr::null_mut(), context: ptr::null_mut(), cursor_hidden: false };
        result.dc = GetDC(window);
        if result.dc.is_null() { return Err("dc".into()); }
        let pfd = PixelFormat::default();
        let format = ChoosePixelFormat(result.dc, &pfd);
        if format == 0 || SetPixelFormat(result.dc, format, &pfd) == 0 { return Err("pixel format".into()); }
        result.context = wglCreateContext(result.dc);
        if result.context.is_null() || wglMakeCurrent(result.dc, result.context) == 0 {
            return Err("wgl".into());
        }
        ShowCursor(0);
        result.cursor_hidden = true;
        Ok(result)
    }

    unsafe fn dimensions(&self) -> Result<[u32; 2], Error> {
        let mut rect = Rect::default();
        if GetClientRect(self.window, &mut rect) == 0 || rect.right <= rect.left || rect.bottom <= rect.top {
            return Err("rect".into());
        }
        Ok([(rect.right - rect.left) as u32, (rect.bottom - rect.top) as u32])
    }

    unsafe fn pump(&self) -> Result<(), Error> {
        let mut message = Message::default();
        while PeekMessageA(&mut message, ptr::null_mut(), 0, 0, 1) != 0 {
            if message.message == 0x12 { return Err("closed".into()); }
            TranslateMessage(&message);
            DispatchMessageA(&message);
        }
        Ok(())
    }
}
impl Drop for Window {
    fn drop(&mut self) { unsafe {
        if !self.context.is_null() {
            wglMakeCurrent(ptr::null_mut(), ptr::null_mut());
            wglDeleteContext(self.context);
        }
        if !self.dc.is_null() { ReleaseDC(self.window, self.dc); }
        if !self.window.is_null() { DestroyWindow(self.window); }
        if self.cursor_hidden { ShowCursor(1); }
    } }
}

struct Playback {
    handle: Handle,
    header: Option<Box<WaveHeader>>,
    pcm: Option<Vec<f32>>,
    prepared: bool,
}

fn mm(result: u32, operation: &str) -> Result<(), Error> {
    #[cfg(feature = "sizecoded")]
    { let _ = operation; if result == 0 { Ok(()) } else { Err("waveout".into()) } }
    #[cfg(not(feature = "sizecoded"))]
    if result == 0 { Ok(()) } else { Err(format!("{operation} failed: MMRESULT={result}")) }
}

impl Playback {
    unsafe fn start(mut pcm: Vec<f32>) -> Result<Self, Error> {
        if pcm.len() != contract::PCM_SAMPLES { return Err("pcm extent".into()); }
        let format = WaveFormat { tag: 3, channels: 2, rate: contract::SAMPLE_RATE,
            bytes_per_second: contract::SAMPLE_RATE * 8, block_align: 8, bits: 32, extra: 0 };
        let header = Box::new(WaveHeader { data: pcm.as_mut_ptr().cast(), bytes: contract::PCM_BYTES as u32,
            recorded: 0, user: 0, flags: 0, loops: 0, next: ptr::null_mut(), reserved: 0 });
        let mut result = Self { handle: ptr::null_mut(), header: Some(header), pcm: Some(pcm), prepared: false };
        mm(waveOutOpen(&mut result.handle, u32::MAX, &format, 0, 0, 0), "waveOutOpen")?;
        mm(waveOutPrepareHeader(result.handle, result.header.as_deref_mut().unwrap(), size_of::<WaveHeader>() as u32), "waveOutPrepareHeader")?;
        result.prepared = true;
        mm(waveOutWrite(result.handle, result.header.as_deref_mut().unwrap(), size_of::<WaveHeader>() as u32), "waveOutWrite")?;
        observe::pcm(7, result.pcm.as_deref().unwrap());
        Ok(result)
    }

    unsafe fn cursor(&self) -> Result<u32, Error> {
        let mut time = MultimediaTime { kind: 2, value: [0; 2] };
        mm(waveOutGetPosition(self.handle, &mut time, size_of::<MultimediaTime>() as u32), "waveOutGetPosition")?;
        if time.kind != 2 { return Err("position".into()); }
        Ok(time.value[0])
    }
}

impl Drop for Playback {
    fn drop(&mut self) { unsafe {
        if self.handle.is_null() { return; }
        let reset = waveOutReset(self.handle);
        let unprepare = if self.prepared {
            waveOutUnprepareHeader(self.handle, self.header.as_deref_mut().unwrap(), size_of::<WaveHeader>() as u32)
        } else { 0 };
        if reset != 0 || unprepare != 0 {
            // A driver may still own these addresses; retain rather than create a use-after-free.
            if let Some(pcm) = self.pcm.take() { core::mem::forget(pcm); }
            if let Some(header) = self.header.take() { Box::leak(header); }
            #[cfg(not(feature = "sizecoded"))]
            eprintln!("waveOut cleanup failed: reset={reset}, unprepare={unprepare}");
            #[cfg(feature = "sizecoded")]
            crate::minimal::message("waveOut cleanup failed:\n");
        }
        let close = waveOutClose(self.handle);
        #[cfg(not(feature = "sizecoded"))]
        if close != 0 { eprintln!("waveOutClose failed: {close}"); }
        #[cfg(feature = "sizecoded")]
        if close != 0 { crate::minimal::message("waveOutClose failed:\n"); }
        let _ = close;
    } }
}

/// The production executable injects the merged standalone audio::render implementation.
/// Rendering runs on a separate thread; its FP mode is exclusively T23-owned.
pub fn run_with_synth(render: RenderPcm) -> Result<(), Error> {
    run(Some(render))
}

/// Controlled 735*n sample cursor with no waveOut/audio; not a production candidate run.
pub fn graphics_diagnostic() -> Result<(), Error> { run(None) }

fn run(render: Option<RenderPcm>) -> Result<(), Error> {
    let mut worker = render.map(synthesis::spawn).transpose()?;
    let mut ready_pcm = None;
    let poll_synth = |worker: &mut Option<synthesis::Worker>, ready: &mut Option<Vec<f32>>| -> Result<(), Error> {
        if worker.as_ref().is_some_and(|w| w.is_finished()) {
            *ready = Some(worker.take().unwrap().join().map_err(|_| Error::from("synth"))??);
        }
        Ok(())
    };
    let _fp = GraphicsFp::enter();
    // Drop order keeps the WGL context alive until Graphics releases all objects.
    let window = unsafe { Window::new()? };
    let mut engine = Engine::default();
    let mut graphics = unsafe { Graphics::new(window.dimensions()?)? };
    let start = unsafe { GetTickCount() };
    while unsafe { GetTickCount() }.wrapping_sub(start) < 1000 {
        poll_synth(&mut worker, &mut ready_pcm)?;
        unsafe { window.pump()?; graphics.loading(window.dc, &mut engine)?; }
    }
    unsafe { graphics.build(window.dc, &mut engine, || {
        poll_synth(&mut worker, &mut ready_pcm)?;
        window.pump()
    })?; }
    #[cfg(feature = "shader-diagnostics")]
    { crate::minimal::message("SHADER_SETUP_PASS\n"); return Ok(()); }
    let playback = if render.is_some() {
        while worker.is_some() {
            poll_synth(&mut worker, &mut ready_pcm)?;
            unsafe { window.pump()?; graphics.loading(window.dc, &mut engine)?; }
            unsafe { Sleep(1); }
        }
        let pcm = ready_pcm.take().ok_or("no pcm")?;
        observe::pcm(6, &pcm);
        Some(unsafe { Playback::start(pcm)? })
    } else { None };
    unsafe { graphics.playback_loading(window.dc, &mut engine)?; }
    let initial = engine.evaluate(0, true).unwrap();
    observe::snapshot(1, &RuntimeSnapshot::frame(0, &initial, engine.records));
    let mut presented: u32 = 0;
    let mut queries: u32 = 0;
    loop {
        unsafe { window.pump()?; }
        let cursor = if let Some(playback) = &playback { unsafe { playback.cursor()? } }
            else { presented.checked_mul(contract::CONTROLLED_STEP).ok_or("cursor")? };
        queries += 1;
        let Some(frame) = engine.evaluate(cursor, true) else {
            observe::snapshot(5, &RuntimeSnapshot::endpoint(presented, contract::Clock::from_samples(cursor), engine.previous_seconds, engine.records));
            #[cfg(feature = "sizecoded")]
            crate::minimal::endpoint(queries, presented, cursor);
            #[cfg(not(feature = "sizecoded"))]
            eprintln!("EIDOLON_RUNTIME mode={} reason=natural_exit queries={queries} frames={presented} terminal_cursor={cursor}",
                if playback.is_some() { "playback" } else { "graphics-diagnostic" });
            break;
        };
        let state = RuntimeSnapshot::frame(presented, &frame, engine.records);
        observe::snapshot(2, &state);
        unsafe {
            graphics.draw(&mut engine, &frame, false)?;
            observe::snapshot(3, &state);
            if SwapBuffers(window.dc) == 0 { return Err("swap".into()); }
        }
        observe::snapshot(4, &state);
        presented += 1;
        if unsafe { GetAsyncKeyState(0x1b) } != 0 { return Err("escape".into()); }
    }
    Ok(())
}
