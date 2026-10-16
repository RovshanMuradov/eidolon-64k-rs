/* Earliest proxy-only rendezvous probe. PAGE_GUARD follows unpacker accesses
 * until execution reaches the post-fixup OEP; hooks would be installed there.
 * Attach uses only kernel/ntdll operations, without loading a DLL or waiting. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdint.h>

static DWORD protection, attaching_tid, pending_tid;
static unsigned guard_events, step_events;
static int enabled;
static int capture_mode, capture_active;
static PVOID handler;
void eidolon_core_initialize(CONTEXT *context);
BOOL eidolon_completion(EXCEPTION_POINTERS *exception);

static void event(const char *result, CONTEXT *context) {
    char path[32768] = {0}, text[1024];
    DWORD n = GetEnvironmentVariableA("EIDOLON_B_LOG", path, sizeof(path));
    if (!n || n >= sizeof(path)) ExitProcess(126);
    HANDLE file = CreateFileA(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                              NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) ExitProcess(126);
    int length = snprintf(text, sizeof(text),
        "{\"event\":\"bootstrap\",\"result\":\"%s\",\"pid\":%lu,\"tid\":%lu,"
        "\"attaching_tid\":%lu,\"eip\":\"0x%08lx\",\"guards\":%u,\"steps\":%u,"
        "\"page_protection\":%lu,\"error\":%lu}\n", result, GetCurrentProcessId(),
        GetCurrentThreadId(), attaching_tid, context ? context->Eip : 0,
        guard_events, step_events, protection, GetLastError());
    DWORD written = 0;
    if (length < 0 || length >= (int)sizeof(text) ||
        !WriteFile(file, text, length, &written, NULL) || written != (DWORD)length ||
        !FlushFileBuffers(file)) ExitProcess(126);
    CloseHandle(file);
}

static LONG CALLBACK rendezvous(EXCEPTION_POINTERS *exception) {
    DWORD code = exception->ExceptionRecord->ExceptionCode;
    CONTEXT *context = exception->ContextRecord;
    DWORD tid = GetCurrentThreadId();
    if (capture_active && eidolon_completion(exception)) return EXCEPTION_CONTINUE_EXECUTION;
    if (!enabled) return EXCEPTION_CONTINUE_SEARCH;
    if (code == EXCEPTION_GUARD_PAGE &&
        exception->ExceptionRecord->NumberParameters >= 2 &&
        exception->ExceptionRecord->ExceptionInformation[1] >= 0x406000 &&
        exception->ExceptionRecord->ExceptionInformation[1] < 0x407000) {
        guard_events++;
        if (tid != attaching_tid || pending_tid || (context->EFlags & 0x100)) {
            event("unsafe_guard_thread_or_nested_step", context);
            ExitProcess(125);
        }
        if (context->Eip == 0x406379) {
            static const BYTE expected[] = {0x55,0x8b,0xec,0x81,0xec,0x24,0x04,0x00,0x00};
            static const BYTE launch[] = {0xff,0x15,0x18,0x90,0x40,0x00};
            if (memcmp((void *)0x406379, expected, sizeof(expected)) ||
                memcmp((void *)0x40639f, launch, sizeof(launch))) {
                event("post_fixup_fingerprint_mismatch", context);
                ExitProcess(125);
            }
            enabled = 0;
            if (capture_mode) {
                eidolon_core_initialize(context);
                capture_active = 1;
                return EXCEPTION_CONTINUE_EXECUTION;
            }
            event("post_fixup_entry_reached_planned_stop", context);
            ExitProcess(0);
        }
        pending_tid = tid;
        context->EFlags |= 0x100;
        return EXCEPTION_CONTINUE_EXECUTION;
    }
    if (code == EXCEPTION_SINGLE_STEP && pending_tid == tid) {
        DWORD old;
        step_events++;
        pending_tid = 0;
        context->EFlags &= ~0x100;
        if (!VirtualProtect((void *)0x406000, 0x1000, protection | PAGE_GUARD, &old)) {
            event("guard_rearm_failed", context);
            ExitProcess(125);
        }
        return EXCEPTION_CONTINUE_EXECUTION;
    }
    return EXCEPTION_CONTINUE_SEARCH;
}

BOOL eidolon_bootstrap_attach(void) {
    char mode[32] = {0};
    if (!GetEnvironmentVariableA("EIDOLON_B_BOOTSTRAP", mode, sizeof(mode))) return TRUE;
    capture_mode = !strcmp(mode, "capture-probe");
    if (!capture_mode && strcmp(mode, "entry-probe")) return FALSE;
    MEMORY_BASIC_INFORMATION mapping = {0};
    attaching_tid = GetCurrentThreadId();
    if (!VirtualQuery((void *)0x406000, &mapping, sizeof(mapping)) ||
        mapping.State != MEM_COMMIT || (mapping.Protect & (PAGE_GUARD | PAGE_NOACCESS))) {
        event("entry_page_unavailable_at_proxy_attach", NULL);
        return FALSE;
    }
    protection = mapping.Protect;
    handler = AddVectoredExceptionHandler(1, rendezvous);
    if (!handler) {
        event("veh_registration_failed", NULL);
        return FALSE;
    }
    enabled = 1;
    DWORD old;
    if (!VirtualProtect((void *)0x406000, 0x1000, protection | PAGE_GUARD, &old)) {
        enabled = 0;
        RemoveVectoredExceptionHandler(handler);
        event("guard_initialization_failed", NULL);
        return FALSE;
    }
    return TRUE;
}
