/* G1a prerequisite: our PE32 proxy must reach a distinct installed Wine DLL.
 * DllMain never loads a backend. Resolve only at an explicit post-loader probe
 * or at the first forwarded API invocation. No original/Wine code is patched. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdint.h>
#include "exports.h"

#ifdef HAS_BOOTSTRAP
BOOL eidolon_bootstrap_attach(void);
#endif

static HMODULE self_module, backend;
static LONG resolving;
static DWORD probe_error;
static BOOL backend_validated;
static const char *probe_result = "not_run";

static void quoted(FILE *out, const char *text) {
    fputc('"', out);
    for (; *text; ++text) {
        unsigned char c = (unsigned char)*text;
        if (c == '"' || c == '\\') fputc('\\', out);
        if (c < 32) fprintf(out, "\\u%04x", c);
        else fputc(c, out);
    }
    fputc('"', out);
}

static void observe(const char *event, const WCHAR *requested, FARPROC symbol,
                    HMODULE owner) {
    char path[MAX_PATH] = {0}, actual[MAX_PATH] = {0};
    char request[MAX_PATH] = {0}, log_path[32768] = {0};
    GetModuleFileNameA(self_module, path, sizeof(path));
    if (backend) GetModuleFileNameA(backend, actual, sizeof(actual));
    if (requested) WideCharToMultiByte(CP_UTF8, 0, requested, -1,
                                     request, sizeof(request), NULL, NULL);
    DWORD length = GetEnvironmentVariableA("EIDOLON_B_LOG", log_path, sizeof(log_path));
    FILE *out = length && length < sizeof(log_path) ? fopen(log_path, "ab") : NULL;
    if (!out) ExitProcess(126);
    fprintf(out, "{\"event\":"); quoted(out, event);
    fprintf(out, ",\"dll\":"); quoted(out, DLL_NAME);
    fprintf(out, ",\"pid\":%lu,\"tid\":%lu,\"self\":\"0x%08lx\",\"backend\":\"0x%08lx\","
                 "\"symbol\":\"0x%08lx\",\"symbol_owner\":\"0x%08lx\",\"error\":%lu,\"result\":",
            GetCurrentProcessId(), GetCurrentThreadId(), (DWORD)(uintptr_t)self_module,
            (DWORD)(uintptr_t)backend, (DWORD)(uintptr_t)symbol,
            (DWORD)(uintptr_t)owner, probe_error);
    quoted(out, probe_result);
    fprintf(out, ",\"self_path\":"); quoted(out, path);
    fprintf(out, ",\"requested_path\":"); quoted(out, request);
    fprintf(out, ",\"backend_path\":"); quoted(out, actual);
    fprintf(out, "}\n");
    if (fflush(out) || fclose(out)) ExitProcess(126);
}

DWORD WINAPI EidolonProbeBackend(void) {
    WCHAR path[MAX_PATH] = {0};
    FARPROC symbol = NULL;
    HMODULE owner = NULL;
    DWORD saved_error = GetLastError();
    if (backend_validated) return 0;
    if (InterlockedCompareExchange(&resolving, 1, 0)) {
        probe_result = "recursive_backend_resolution";
        probe_error = ERROR_INVALID_FUNCTION;
        observe("backend_probe", NULL, NULL, NULL);
        return 125;
    }
    DWORD length = GetEnvironmentVariableW(L"EIDOLON_B_BACKEND", path, MAX_PATH);
    if (!length) {
        UINT n = GetSystemDirectoryW(path, MAX_PATH);
        if (!n || n + sizeof(DLL_NAME) + 1 >= MAX_PATH) {
            probe_result = "system_directory_failure";
            probe_error = GetLastError();
            goto done;
        }
        lstrcatW(path, L"\\" DLL_WNAME);
    } else if (length >= MAX_PATH) {
        probe_result = "backend_path_too_long";
        probe_error = ERROR_INSUFFICIENT_BUFFER;
        goto done;
    }
    SetLastError(0);
    backend = LoadLibraryW(path);
    probe_error = GetLastError();
    if (!backend) {
        probe_result = "backend_load_failed";
        goto done;
    }
    /* Resolving an address is safe even for self; never CALL it unless distinct. */
    symbol = GetProcAddress(backend, CANARY_SYMBOL);
    if (symbol) GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                                  GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                                  (LPCSTR)(uintptr_t)symbol, &owner);
    if (backend == self_module) {
        probe_result = "backend_is_proxy";
    } else if (!symbol || !owner || owner == self_module) {
        probe_result = "backend_symbol_missing_or_self";
    } else {
        probe_result = "distinct_backend";
        backend_validated = TRUE;
    }
done:
    observe("backend_probe", path, symbol, owner);
    InterlockedExchange(&resolving, 0);
    SetLastError(saved_error);
    return strcmp(probe_result, "distinct_backend") ? 125 : 0;
}

/* Generated assembly preserves argument stack, integer registers/EFLAGS and
 * FXSAVE state while this function locates the untouched backend export. */
FARPROC __cdecl eidolon_resolve(unsigned index) {
    DWORD saved_error = GetLastError();
    if (index >= EXPORT_COUNT || EidolonProbeBackend()) ExitProcess(125);
    FARPROC target = GetProcAddress(backend, (LPCSTR)(uintptr_t)export_ordinals[index]);
    HMODULE owner = NULL;
    if (!target || !GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                                      GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                                      (LPCSTR)(uintptr_t)target, &owner) || owner == self_module) {
        probe_result = "unresolved_or_recursive_export";
        probe_error = GetLastError();
        observe("forward_failure", NULL, target, owner);
        ExitProcess(125);
    }
    SetLastError(saved_error);
    return target;
}

BOOL WINAPI DllMain(HINSTANCE module, DWORD reason, LPVOID reserved) {
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        self_module = module;
        DisableThreadLibraryCalls(module);
#ifdef HAS_BOOTSTRAP
        return eidolon_bootstrap_attach();
#endif
    }
    return TRUE;
}
