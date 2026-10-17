//! Engine-owned PCM allocation/thread seam shared by playback and CPU diagnostics.
use crate::{audio, contract};
use alloc::{vec, vec::Vec};
use crate::RuntimeError as Error;
#[cfg(not(all(feature = "sizecoded", target_os = "windows")))]
use std::thread;

pub type RenderPcm = fn(&mut [f32]) -> Result<(), &'static str>;
#[cfg(not(all(feature = "sizecoded", target_os = "windows")))]
pub type Worker = thread::JoinHandle<Result<Vec<f32>, Error>>;
#[cfg(all(feature = "sizecoded", target_os = "windows"))]
pub use minimal_worker::{Worker, spawn};

const _: () = {
    assert!(audio::SAMPLE_RATE == contract::SAMPLE_RATE);
    assert!(audio::CHANNELS == contract::CHANNELS);
    assert!(audio::TOTAL_FRAMES as usize == contract::PCM_FRAMES);
};

/// Only a successful complete render returns its allocation to the playback thread.
#[cfg(not(all(feature = "sizecoded", target_os = "windows")))]
pub fn spawn(render: RenderPcm) -> Result<Worker, Error> {
    thread::Builder::new().name("eidolon-synth".into()).spawn(move || {
        let mut pcm = vec![0.0_f32; contract::PCM_SAMPLES];
        render(&mut pcm).map_err(str::to_owned)?;
        Ok(pcm)
    }).map_err(|error| format!("could not start synthesis worker: {error}"))
}

#[cfg(all(feature = "sizecoded", target_os = "windows"))]
mod minimal_worker {
    use super::*;
    use alloc::boxed::Box;
    use crate::windows::*;
    struct Job { render: RenderPcm, result: Option<Result<Vec<f32>, Error>> }
    pub struct Worker { handle: Handle, job: *mut Job }
    unsafe extern "system" fn run(parameter: Handle) -> u32 {
        let job = &mut *parameter.cast::<Job>();
        let mut pcm = vec![0.0; contract::PCM_SAMPLES];
        job.result = Some((job.render)(&mut pcm).map(|()| pcm).map_err(Error::from));
        0
    }
    pub fn spawn(render: RenderPcm) -> Result<Worker, Error> {
        unsafe {
            let job = Box::into_raw(Box::new(Job { render, result: None }));
            let handle = CreateThread(core::ptr::null_mut(), 2 * 1024 * 1024, run,
                job.cast(), 0, core::ptr::null_mut());
            if handle.is_null() { drop(Box::from_raw(job)); return Err("thread".into()); }
            Ok(Worker { handle, job })
        }
    }
    impl Worker {
        pub fn is_finished(&self) -> bool { unsafe { WaitForSingleObject(self.handle, 0) == 0 } }
        pub fn join(mut self) -> Result<Result<Vec<f32>, Error>, ()> {
            unsafe {
                if WaitForSingleObject(self.handle, u32::MAX) != 0 { return Err(()); }
                let result = (*self.job).result.take().ok_or(());
                drop(Box::from_raw(self.job));
                self.job = core::ptr::null_mut();
                result
            }
        }
    }
    impl Drop for Worker {
        fn drop(&mut self) { unsafe {
            // On early exit a detached worker still owns Job; do not free live memory.
            CloseHandle(self.handle);
        } }
    }
}
