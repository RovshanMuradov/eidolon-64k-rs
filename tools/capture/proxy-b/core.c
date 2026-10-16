/* Original-only instrumentation installed at the validated post-fixup entry.
 * Wine APIs and Wine files remain untouched. All clocks exposed to the demo
 * are routed through its own resolved slots, not through kernel DLL patches. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <mmsystem.h>
#include <wincrypt.h>
#include <GL/gl.h>
#include <stdio.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdlib.h>

extern void eidolon_gettick(void), eidolon_qpc(void), eidolon_qpf(void);
extern void eidolon_position(void), eidolon_swap(void), eidolon_create_thread(void);
extern void eidolon_wave_open(void), eidolon_wave_prepare(void), eidolon_wave_write(void);
extern void eidolon_lookup(void), eidolon_wgl_lookup(void), eidolon_timegettime(void);

static CRITICAL_SECTION lock;
static HANDLE synth_event;
static DWORD seq, main_tid, synth_tid, frame, startup, epoch, initial_tick, final_tick;
static DWORD final_cursor, submitted_bytes, submitted_base, stop_frames;
static LONG completion_count;
static BOOL timeline, acquired;
static char folder[32768], log_path[32768], pcm_sha[65], stable_sha[65];
static FARPROC real_swap, real_create_thread, real_wave_open, real_wave_prepare, real_wave_write;
static FARPROC real_position, real_lookup, real_wgl_lookup;
static BYTE completion_original;
static void *pixels;
static DWORD pixel_bytes;
static HMODULE gl_module;
static void (APIENTRY *get_integer)(GLenum, GLint *);
static void (APIENTRY *pixel_store)(GLenum, GLint);
static void (APIENTRY *read_buffer)(GLenum);
static void (APIENTRY *read_pixels)(GLint,GLint,GLsizei,GLsizei,GLenum,GLenum,void *);
static GLenum (APIENTRY *get_error)(void);
static HGLRC (WINAPI *get_context)(void);
static HDC (WINAPI *get_dc)(void);
static void (APIENTRY *bind_buffer)(GLenum,GLuint);
static void (APIENTRY *get_attachment)(GLenum,GLenum,GLenum,GLint *);

static void fail(const char *reason);

static void hash(const void *data, DWORD size, char output[65]) {
    HCRYPTPROV provider = 0;
    HCRYPTHASH digest = 0;
    BYTE bytes[32]; DWORD length = sizeof(bytes);
    if (!CryptAcquireContextA(&provider, NULL, NULL, PROV_RSA_AES, CRYPT_VERIFYCONTEXT) ||
        !CryptCreateHash(provider, CALG_SHA_256, 0, 0, &digest) ||
        !CryptHashData(digest, data, size, 0) ||
        !CryptGetHashParam(digest, HP_HASHVAL, bytes, &length, 0) || length != 32)
        ExitProcess(126);
    for (unsigned i = 0; i < 32; ++i) sprintf(output + 2*i, "%02x", bytes[i]);
    CryptDestroyHash(digest);
    CryptReleaseContext(provider, 0);
}

static void file_write(const char *path, const void *data, DWORD size, BOOL append) {
    HANDLE file = CreateFileA(path, append ? FILE_APPEND_DATA : GENERIC_WRITE,
                             FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,
                             append ? OPEN_ALWAYS : CREATE_NEW, FILE_ATTRIBUTE_NORMAL, NULL);
    DWORD written = 0;
    if (file == INVALID_HANDLE_VALUE || !WriteFile(file, data, size, &written, NULL) ||
        written != size || !FlushFileBuffers(file)) ExitProcess(126);
    CloseHandle(file);
}

static DWORD record(const char *event, const char *fields, ...) {
    char body[3072], text[4096];
    va_list args;
    va_start(args, fields);
    int count = vsnprintf(body, sizeof(body), fields, args);
    va_end(args);
    if (count < 0 || count >= (int)sizeof(body)) ExitProcess(126);
    EnterCriticalSection(&lock);
    DWORD id = ++seq;
    count = snprintf(text, sizeof(text), "{\"seq\":%lu,\"event\":\"%s\",\"pid\":%lu,\"tid\":%lu%s}\n",
                     id, event, GetCurrentProcessId(), GetCurrentThreadId(), body);
    if (count < 0 || count >= (int)sizeof(text)) ExitProcess(126);
    file_write(log_path, text, count, TRUE);
    LeaveCriticalSection(&lock);
    return id;
}

static void fail(const char *reason) {
    record("failure", ",\"reason\":\"%s\",\"error\":%lu", reason, GetLastError());
    ExitProcess(125);
}

static void replace(DWORD address, const void *data, SIZE_T size) {
    DWORD old, ignored;
    if (!VirtualProtect((void *)(uintptr_t)address, size, PAGE_EXECUTE_READWRITE, &old)) fail("protect_hook");
    memcpy((void *)(uintptr_t)address, data, size);
    if (!FlushInstructionCache(GetCurrentProcess(), (void *)(uintptr_t)address, size) ||
        !VirtualProtect((void *)(uintptr_t)address, size, old, &ignored)) fail("finish_hook");
}

static void slot(DWORD address, FARPROC target, FARPROC *original) {
    if (original) *original = *(FARPROC *)(uintptr_t)address;
    replace(address, &target, sizeof(target));
    record("route", ",\"slot\":\"0x%08lx\",\"target\":\"0x%08lx\"", address, (DWORD)(uintptr_t)target);
}

static DWORD clock_ms(void) { return timeline ? epoch + (DWORD)((uint64_t)frame * 1000 / 60) : startup; }

DWORD core_gettick(DWORD *stack) {
    DWORD value = clock_ms();
    record("clock", ",\"api\":\"GetTickCount\",\"caller\":\"0x%08lx\",\"n\":%lu,\"value\":%lu,\"timeline\":%s",
           stack[0], frame, value, timeline ? "true" : "false");
    if (!timeline) startup++;
    return value;
}
DWORD core_timegettime(DWORD *stack) {
    DWORD value = clock_ms();
    record("clock", ",\"api\":\"timeGetTime\",\"caller\":\"0x%08lx\",\"n\":%lu,\"value\":%lu", stack[0], frame, value);
    return value;
}
DWORD core_qpc(DWORD *stack) {
    LARGE_INTEGER *out = (void *)(uintptr_t)stack[1];
    out->QuadPart = timeline ? (uint64_t)epoch * 60000 + (uint64_t)frame * 1000000 : (uint64_t)startup * 60000;
    record("clock", ",\"api\":\"QueryPerformanceCounter\",\"caller\":\"0x%08lx\",\"n\":%lu,\"value\":%lld", stack[0], frame, out->QuadPart);
    return TRUE;
}
DWORD core_qpf(DWORD *stack) {
    LARGE_INTEGER *out = (void *)(uintptr_t)stack[1]; out->QuadPart = 60000000;
    record("clock", ",\"api\":\"QueryPerformanceFrequency\",\"caller\":\"0x%08lx\",\"value\":60000000", stack[0]);
    return TRUE;
}

DWORD core_create_thread(DWORD *s) {
    if (s[3] != 0x401636 || completion_count || synth_tid) fail("unexpected_synth_launch");
    initial_tick = *(DWORD *)0xb16bd20;
    if (initial_tick != 1) fail("initial_tick_not_one");
    record("synth_launch", ",\"caller\":\"0x%08lx\",\"entry\":\"0x%08lx\",\"initial_tick\":%lu", s[0], s[3], initial_tick);
    DWORD thread_id = 0;
    HANDLE thread = ((HANDLE (WINAPI *)(LPSECURITY_ATTRIBUTES,SIZE_T,LPTHREAD_START_ROUTINE,LPVOID,DWORD,LPDWORD))(uintptr_t)real_create_thread)
        ((void *)(uintptr_t)s[1], s[2], (void *)(uintptr_t)s[3], (void *)(uintptr_t)s[4], s[5], &thread_id);
    if (!thread) fail("synth_CreateThread_failed");
    synth_tid = thread_id;
    if (s[6]) *(DWORD *)(uintptr_t)s[6] = thread_id;
    record("synth_thread", ",\"synth_tid\":%lu", synth_tid);
    return (DWORD)(uintptr_t)thread;
}

DWORD core_wave_open(DWORD *s) {
    WAVEFORMATEX *format = (void *)(uintptr_t)s[3];
    if (format->wFormatTag != 3 || format->nChannels != 2 || format->nSamplesPerSec != 44100 ||
        format->wBitsPerSample != 32 || format->nBlockAlign != 8) fail("PCM_format");
    DWORD result = ((MMRESULT (WINAPI *)(LPHWAVEOUT,UINT,LPCWAVEFORMATEX,DWORD_PTR,DWORD_PTR,DWORD))(uintptr_t)real_wave_open)
        ((void *)(uintptr_t)s[1], s[2], format, s[4], s[5], s[6]);
    record("wave_open", ",\"result\":%lu,\"format\":\"f32le\",\"channels\":2,\"rate\":44100", result);
    if (result) fail("waveOutOpen_failed");
    return result;
}
DWORD core_wave_prepare(DWORD *s) {
    DWORD result = ((MMRESULT (WINAPI *)(HWAVEOUT,LPWAVEHDR,UINT))(uintptr_t)real_wave_prepare)
        ((void *)(uintptr_t)s[1], (void *)(uintptr_t)s[2], s[3]);
    record("wave_prepare", ",\"result\":%lu", result);
    if (result) fail("waveOutPrepareHeader_failed");
    return result;
}
DWORD core_wave_write(DWORD *s) {
    WAVEHDR *header = (void *)(uintptr_t)s[2];
    submitted_base = (DWORD)(uintptr_t)header->lpData;
    submitted_bytes = header->dwBufferLength;
    if (submitted_bytes != 159716352) fail("PCM_submission_extent");
    DWORD result = ((MMRESULT (WINAPI *)(HWAVEOUT,LPWAVEHDR,UINT))(uintptr_t)real_wave_write)
        ((void *)(uintptr_t)s[1], header, s[3]);
    record("wave_write", ",\"result\":%lu,\"base\":\"0x%08lx\",\"bytes\":%lu", result, submitted_base, submitted_bytes);
    if (result) fail("waveOutWrite_failed");
    return result;
}

static void acquire(void) {
    record("timeline_gate_enter", ",\"completion_count\":%ld", completion_count);
    if (WaitForSingleObject(synth_event, 240000) != WAIT_OBJECT_0) fail("synth_gate_timeout");
    if (completion_count != 1 || final_tick != 19964545 ||
        final_cursor - submitted_base != submitted_bytes) fail("PCM_completion_extent");
    char path[32768];
    if (snprintf(path, sizeof(path), "%s/pcm.f32le", folder) >= (int)sizeof(path)) fail("output_path");
    record("readback_begin", ",\"base\":\"0x%08lx\",\"bytes\":%lu", submitted_base, submitted_bytes);
    file_write(path, (void *)(uintptr_t)submitted_base, submitted_bytes, FALSE);
    hash((void *)(uintptr_t)submitted_base, submitted_bytes, pcm_sha);
    record("readback_end", ",\"sha256\":\"%s\"", pcm_sha);
    /* Separate later read of the original source range, not the saved file. */
    hash((void *)(uintptr_t)submitted_base, submitted_bytes, stable_sha);
    record("stability_check", ",\"sha256\":\"%s\",\"bytes\":%lu", stable_sha, submitted_bytes);
    if (strcmp(pcm_sha, stable_sha)) fail("PCM_changed_after_completion");
    acquired = TRUE;
}

DWORD core_position(DWORD *s) {
    if (s[0] != 0x407b97) fail("unknown_position_caller");
    if (!acquired) acquire();
    if (!timeline) { epoch = startup; timeline = TRUE; record("epoch", ",\"E\":%lu", epoch); }
    MMTIME *position = (void *)(uintptr_t)s[2];
    if (s[3] != sizeof(MMTIME) || position->wType != TIME_SAMPLES) fail("position_type");
    position->wType = TIME_SAMPLES;
    position->u.sample = frame * 735;
    record("clock", ",\"api\":\"waveOutGetPosition\",\"caller\":\"0x%08lx\",\"n\":%lu,\"value\":%lu,\"wType\":2", s[0], frame, frame * 735);
    return MMSYSERR_NOERROR;
}

static FARPROC routed_name(const char *name) {
    if ((uintptr_t)name < 65536) return NULL;
    if (!strcmp(name, "GetTickCount")) return (FARPROC)eidolon_gettick;
    if (!strcmp(name, "timeGetTime")) return (FARPROC)eidolon_timegettime;
    if (!strcmp(name, "QueryPerformanceCounter")) return (FARPROC)eidolon_qpc;
    if (!strcmp(name, "QueryPerformanceFrequency")) return (FARPROC)eidolon_qpf;
    if (!strcmp(name, "SwapBuffers") || !strcmp(name, "wglSwapBuffers")) return (FARPROC)eidolon_swap;
    return NULL;
}
DWORD core_lookup(DWORD *s) {
    const char *name = (void *)(uintptr_t)s[2];
    FARPROC result = routed_name(name);
    if (!result) result = ((FARPROC (WINAPI *)(HMODULE,LPCSTR))(uintptr_t)real_lookup)((void *)(uintptr_t)s[1], name);
    record("lookup", ",\"api\":\"GetProcAddress\",\"ordinal\":%s,\"name\":\"%s\",\"routed\":%s",
           (uintptr_t)name < 65536 ? "true" : "false", (uintptr_t)name < 65536 ? "" : name, routed_name(name) ? "true" : "false");
    return (DWORD)(uintptr_t)result;
}
DWORD core_wgl_lookup(DWORD *s) {
    const char *name = (void *)(uintptr_t)s[1];
    FARPROC result = ((FARPROC (WINAPI *)(LPCSTR))(uintptr_t)real_wgl_lookup)(name);
    record("lookup", ",\"api\":\"wglGetProcAddress\",\"name\":\"%s\",\"resolved\":%s", name, result ? "true" : "false");
    return (DWORD)(uintptr_t)result;
}

static void gl_initialize(void) {
    WCHAR path[MAX_PATH];
    if (!GetSystemDirectoryW(path, MAX_PATH)) fail("GL_system_directory");
    lstrcatW(path, L"\\opengl32.dll");
    gl_module = LoadLibraryW(path);
    if (!gl_module) fail("GL_backend");
#define LOAD_GL_API(variable, name) do { *(FARPROC *)&variable = GetProcAddress(gl_module, name); if (!variable) fail(name); } while (0)
    LOAD_GL_API(get_integer, "glGetIntegerv"); LOAD_GL_API(pixel_store, "glPixelStorei");
    LOAD_GL_API(read_buffer, "glReadBuffer"); LOAD_GL_API(read_pixels, "glReadPixels");
    LOAD_GL_API(get_error, "glGetError"); LOAD_GL_API(get_context, "wglGetCurrentContext");
    LOAD_GL_API(get_dc, "wglGetCurrentDC");
#undef LOAD_GL_API
    bind_buffer = (void *)((PROC (WINAPI *)(LPCSTR))(uintptr_t)real_wgl_lookup)("glBindBuffer");
    get_attachment = (void *)((PROC (WINAPI *)(LPCSTR))(uintptr_t)real_wgl_lookup)("glGetFramebufferAttachmentParameteriv");
    if (!bind_buffer || !get_attachment) fail("GL_extensions");
}

static void capture(HDC dc) {
    if (!gl_module) gl_initialize();
    if (!get_context() || get_dc() != dc) fail("GL_owning_context");
    HGLRC context = get_context();
    const GLenum queries[] = {0x8ca6,0x8caa,GL_READ_BUFFER,GL_PACK_ALIGNMENT,GL_PACK_ROW_LENGTH,
                              GL_PACK_SKIP_ROWS,GL_PACK_SKIP_PIXELS,GL_PACK_SWAP_BYTES,GL_PACK_LSB_FIRST,
                              0x806c,0x806b,0x88ed,GL_RED_BITS,GL_GREEN_BITS,GL_BLUE_BITS,GL_ALPHA_BITS,0x80a9,0x8db9};
    GLint before[sizeof(queries)/sizeof(*queries)], after[sizeof(queries)/sizeof(*queries)];
    GLenum prior = get_error();
    for (unsigned i=0;i<sizeof(queries)/sizeof(*queries);++i) get_integer(queries[i], &before[i]);
    if (prior || get_error()) fail("GL_initial_error");
    if (before[0] || before[1]) fail("nondefault_final_framebuffer");
    if (before[12] != 8 || before[13] != 8 || before[14] != 8 || before[15] != 8 || before[16]) fail("unsupported_final_components_or_samples");
    GLint encoding, component;
    get_attachment(0x8d40, GL_BACK_LEFT, 0x8210, &encoding);
    get_attachment(0x8d40, GL_BACK_LEFT, 0x8211, &component);
    if (get_error() || component != 0x8c17) fail("unsupported_final_component_type");
    DWORD width = *(DWORD *)0xb17bf2c, height = *(DWORD *)0xb17bfac;
    if (width != 1920 || height != 1080) fail("final_dimensions");
    if (!pixels) {
        pixel_bytes = width * height * 4;
        pixels = VirtualAlloc(NULL, pixel_bytes, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        if (!pixels) fail("frame_allocation");
    }
    if (before[11]) bind_buffer(0x88eb, 0);
    read_buffer(GL_BACK);
    pixel_store(GL_PACK_ALIGNMENT, 1);
    for (unsigned i=4;i<=10;++i) pixel_store(queries[i], 0);
    read_pixels(0,0,width,height,GL_RGBA,GL_UNSIGNED_BYTE,pixels);
    GLenum read_error = get_error();
    read_buffer(before[2]);
    for (unsigned i=3;i<=10;++i) pixel_store(queries[i], before[i]);
    if (before[11]) bind_buffer(0x88eb, before[11]);
    for (unsigned i=0;i<sizeof(queries)/sizeof(*queries);++i) get_integer(queries[i], &after[i]);
    if (read_error || get_error() || memcmp(before,after,sizeof(before)) || get_context()!=context || get_dc()!=dc)
        fail("GL_readback_state_or_error");
    char state_hash[65], digest[65], path[32768];
    hash(before,sizeof(before),state_hash); hash(pixels,pixel_bytes,digest);
    if (snprintf(path,sizeof(path),"%s/frame-%05lu.rgba",folder,frame)>=(int)sizeof(path)) fail("frame_path");
    file_write(path,pixels,pixel_bytes,FALSE);
    record("pre_present", ",\"n\":%lu,\"clock_tick\":%lu,\"audio_position\":%lu,\"sha256\":\"%s\","
           "\"width\":%lu,\"height\":%lu,\"row_order\":\"bottom-up\",\"format\":\"rgba8\","
           "\"encoding\":%ld,\"component\":%ld,\"samples\":%ld,\"sRGB_enabled\":%ld,"
           "\"before_state_sha256\":\"%s\",\"after_state_sha256\":\"%s\",\"state_equal\":true",
           frame,frame,frame*735,digest,width,height,encoding,component,before[16],before[17],state_hash,state_hash);
}

DWORD core_swap(DWORD *s) {
    if (s[0] != 0x406374 && s[0] != 0x408603) fail("unknown_present_route");
    BOOL is_timeline = s[0] == 0x408603;
    if (is_timeline) {
        if (!timeline || !acquired) fail("present_before_clock_or_pcm");
        capture((void *)(uintptr_t)s[1]);
    }
    BOOL result = ((BOOL (WINAPI *)(HDC))(uintptr_t)real_swap)((void *)(uintptr_t)s[1]);
    if (!result) fail("SwapBuffers_failed");
    if (is_timeline) {
        record("post_present", ",\"n\":%lu,\"result\":true", frame);
        frame++;
        if (frame == stop_frames) {
            record("planned_partial_stop", ",\"frames\":%lu,\"exit_code\":0,\"finalized\":false", frame);
            ExitProcess(0);
        }
    }
    return result;
}

BOOL eidolon_completion(EXCEPTION_POINTERS *exception) {
    if (exception->ExceptionRecord->ExceptionCode != EXCEPTION_BREAKPOINT ||
        exception->ExceptionRecord->ExceptionAddress != (void *)0x401765) return FALSE;
    CONTEXT *context = exception->ContextRecord, before = *context;
    if (GetCurrentThreadId() != synth_tid || InterlockedIncrement(&completion_count) != 1) fail("completion_thread_or_count");
    final_tick = *(DWORD *)0xb16bd20;
    final_cursor = *(DWORD *)(uintptr_t)(context->Ebp + 8);
    record("synth_complete", ",\"site\":\"0x00401765\",\"synth_tid\":%lu,\"initial_tick\":%lu,"
           "\"final_tick\":%lu,\"final_cursor\":\"0x%08lx\"", synth_tid,initial_tick,final_tick,final_cursor);
    replace(0x401765, &completion_original, 1);
    if (memcmp(&before,context,sizeof(before))) fail("completion_context_changed");
    char digest[65]; hash(&before,sizeof(before),digest);
    record("hook_context", ",\"site\":\"0x00401765\",\"before_sha256\":\"%s\",\"after_sha256\":\"%s\",\"equal\":true",digest,digest);
    context->Eip = 0x401765;
    if (!SetEvent(synth_event)) fail("signal_completion");
    return TRUE;
}

void eidolon_core_initialize(CONTEXT *context) {
    InitializeCriticalSection(&lock);
    main_tid = GetCurrentThreadId();
    DWORD size = GetEnvironmentVariableA("EIDOLON_B_LOG",log_path,sizeof(log_path));
    if (!size || size>=sizeof(log_path)) ExitProcess(126);
    size = GetEnvironmentVariableA("EIDOLON_B_OUTPUT",folder,sizeof(folder));
    if (!size || size>=sizeof(folder)) fail("output_directory");
    char setting[32] = {0};
    GetEnvironmentVariableA("EIDOLON_B_FRAMES",setting,sizeof(setting));
    stop_frames = strtoul(setting,NULL,10);
    if (!stop_frames || stop_frames>600) fail("diagnostic_frame_limit");
    synth_event = CreateEventA(NULL,TRUE,FALSE,NULL);
    if (!synth_event) fail("create_completion_event");
    static const BYTE completion[] = {0x5f,0x5e,0x8b,0xe5,0x5d,0xc3};
    BOOL bad = GetEnvironmentVariableA("EIDOLON_B_BAD_FINGERPRINT",setting,sizeof(setting)) != 0;
    if (bad || memcmp((void *)0x401765,completion,sizeof(completion))) fail("completion_fingerprint_rejected_before_patch");
    char fingerprint[65], context_hash[65];
    hash((void *)0x401000,0x7647,fingerprint); hash(context,sizeof(*context),context_hash);
    record("bootstrap_before_synth", ",\"site\":\"0x00406379\",\"mapping_sha256\":\"%s\",\"context_sha256\":\"%s\",\"initial_tick_before_init\":%lu",fingerprint,context_hash,*(DWORD *)0xb16bd20);
    completion_original = *(BYTE *)0x401765;
    BYTE trap = 0xcc; replace(0x401765,&trap,1);
    slot(0x409018,(FARPROC)eidolon_create_thread,&real_create_thread);
    slot(0x409024,(FARPROC)eidolon_gettick,NULL);
    slot(0x409008,(FARPROC)eidolon_swap,&real_swap);
    slot(0x409090,(FARPROC)eidolon_wave_open,&real_wave_open);
    slot(0x40908c,(FARPROC)eidolon_wave_prepare,&real_wave_prepare);
    slot(0x409094,(FARPROC)eidolon_wave_write,&real_wave_write);
    slot(0x409098,(FARPROC)eidolon_position,&real_position);
    slot(0x409050,(FARPROC)eidolon_wgl_lookup,&real_wgl_lookup);
    HMODULE kernel = GetModuleHandleA("kernel32.dll");
    FARPROC qpc = GetProcAddress(kernel,"QueryPerformanceCounter"), qpf = GetProcAddress(kernel,"QueryPerformanceFrequency");
    real_lookup = GetProcAddress(kernel,"GetProcAddress");
    for (DWORD address=0x409000;address<=0x409098;address+=4) {
        FARPROC current=*(FARPROC *)(uintptr_t)address;
        if (current==qpc) slot(address,(FARPROC)eidolon_qpc,NULL);
        if (current==qpf) slot(address,(FARPROC)eidolon_qpf,NULL);
        if (current==real_lookup) slot(address,(FARPROC)eidolon_lookup,NULL);
    }
    record("hooks_installed", ",\"main_tid\":%lu,\"synth_not_launched\":true",main_tid);
}
