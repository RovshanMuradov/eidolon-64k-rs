#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>

/* Diagnostic debugger, launched only through tools/wine-headless. */
static HANDLE process;
static const char *out;
static DWORD main_teb;
typedef struct { DWORD address; BYTE saved; int armed; } Breakpoint;
static Breakpoint breaks[] = {
    {0x3ee944, 0, 0}, {0x3f94a4, 0, 0}, {0x40121f, 0, 0},
    {0x401225, 0, 0}, {0x401244, 0, 0}, {0x4012e5, 0, 0},
    {0x405b46, 0, 0}, {0x406379, 0, 0}
};

static DWORD word(DWORD address) {
    DWORD value = 0;
    SIZE_T n;
    if (!ReadProcessMemory(process, (void *)(uintptr_t)address, &value, 4, &n))
        printf("READ_ERROR address=%08lx error=%lu\n", address, GetLastError());
    return value;
}

static void arm(unsigned i, BYTE expected) {
    SIZE_T n;
    BYTE trap = 0xcc;
    Breakpoint *b = &breaks[i];
    if (!ReadProcessMemory(process, (void *)(uintptr_t)b->address, &b->saved, 1, &n) || b->saved != expected ||
        !WriteProcessMemory(process, (void *)(uintptr_t)b->address, &trap, 1, &n)) {
        printf("BREAKPOINT_ERROR address=%08lx actual=%02x expected=%02x\n", b->address, b->saved, expected);
        TerminateProcess(process, 2);
    } else {
        FlushInstructionCache(process, (void *)(uintptr_t)b->address, 1);
        b->armed = 1;
    }
}

static void dump(const char *tag, DWORD address, DWORD length) {
    char path[1024];
    unsigned char bytes[4096];
    snprintf(path, sizeof(path), "%s/%s-%08lx.bin", out, tag, address);
    FILE *f = fopen(path, "wb");
    if (!f) { perror(path); exit(2); }
    DWORD total = 0;
    for (DWORD offset = 0; offset < length; offset += sizeof(bytes)) {
        SIZE_T got = 0;
        DWORD n = length - offset;
        if (n > sizeof(bytes)) n = sizeof(bytes);
        if (!ReadProcessMemory(process, (void *)(uintptr_t)(address + offset), bytes, n, &got))
            break;
        fwrite(bytes, 1, got, f);
        total += got;
    }
    fclose(f);
    printf("DUMP %s address=%08lx size=%08lx requested=%08lx\n", tag, address, total, length);
}

static void context(DWORD tid, CONTEXT *c) {
    HANDLE thread = OpenThread(THREAD_ALL_ACCESS, FALSE, tid);
    c->ContextFlags = CONTEXT_ALL;
    if (!thread || !GetThreadContext(thread, c)) {
        printf("CONTEXT_ERROR %lu\n", GetLastError()); exit(2);
    }
    CloseHandle(thread);
    DWORD mxcsr;
    memcpy(&mxcsr, c->ExtendedRegisters + 24, 4);
    printf("CONTEXT tid=%04lx eip=%08lx esp=%08lx ebp=%08lx eax=%08lx ebx=%08lx ecx=%08lx edx=%08lx esi=%08lx edi=%08lx flags=%08lx mxcsr=%08lx x87=%04lx\n",
           tid, c->Eip, c->Esp, c->Ebp, c->Eax, c->Ebx, c->Ecx, c->Edx, c->Esi, c->Edi, c->EFlags, mxcsr, c->FloatSave.ControlWord);
}

int main(int argc, char **argv) {
    if (argc != 3) { fprintf(stderr, "usage: debug-native.exe TARGET OUTPUT_DIRECTORY\n"); return 2; }
    out = argv[2];
    setvbuf(stdout, NULL, _IONBF, 0);
    STARTUPINFOA si = {0};
    PROCESS_INFORMATION pi = {0};
    si.cb = sizeof(si);
    char command[2048];
    snprintf(command, sizeof(command), "\"%s\"", argv[1]);
    if (!CreateProcessA(argv[1], command, NULL, NULL, FALSE, DEBUG_ONLY_THIS_PROCESS, NULL, NULL, &si, &pi)) {
        printf("CREATE_ERROR %lu\n", GetLastError()); return 2;
    }
    process = pi.hProcess;
    printf("START pid=%04lx tid=%04lx\n", pi.dwProcessId, pi.dwThreadId);
    DWORD start = GetTickCount();
    int diagnosed = 0;
    for (;;) {
        DEBUG_EVENT ev;
        if (!WaitForDebugEvent(&ev, 1000)) {
            if (GetTickCount() - start > 120000) { TerminateProcess(process, 124); diagnosed = 1; }
            continue;
        }
        DWORD disposition = DBG_CONTINUE;
        if (ev.dwDebugEventCode == CREATE_PROCESS_DEBUG_EVENT) {
            printf("PROCESS base=%p entry=%p\n", ev.u.CreateProcessInfo.lpBaseOfImage, ev.u.CreateProcessInfo.lpStartAddress);
            main_teb = (DWORD)(uintptr_t)ev.u.CreateProcessInfo.lpThreadLocalBase;
            if (ev.u.CreateProcessInfo.hFile) CloseHandle(ev.u.CreateProcessInfo.hFile);
            arm(0, 0xc3);
        } else if (ev.dwDebugEventCode == CREATE_THREAD_DEBUG_EVENT) {
            printf("THREAD tid=%04lx entry=%p tls=%p\n", ev.dwThreadId, ev.u.CreateThread.lpStartAddress, ev.u.CreateThread.lpThreadLocalBase);
            CloseHandle(ev.u.CreateThread.hThread);
        } else if (ev.dwDebugEventCode == LOAD_DLL_DEBUG_EVENT) {
            char name[1024] = {0};
            if (ev.u.LoadDll.hFile) {
                GetFinalPathNameByHandleA(ev.u.LoadDll.hFile, name, sizeof(name), 0);
                CloseHandle(ev.u.LoadDll.hFile);
            }
            printf("DLL base=%p file=%s\n", ev.u.LoadDll.lpBaseOfDll, name);
        } else if (ev.dwDebugEventCode == EXCEPTION_DEBUG_EVENT) {
            EXCEPTION_RECORD *e = &ev.u.Exception.ExceptionRecord;
            printf("EXCEPTION tid=%04lx code=%08lx address=%p first=%lu info=%08lx,%08lx\n", ev.dwThreadId,
                   e->ExceptionCode, e->ExceptionAddress, ev.u.Exception.dwFirstChance,
                   e->ExceptionInformation[0], e->ExceptionInformation[1]);
            Breakpoint *hit = NULL;
            for (unsigned i = 0; i < sizeof(breaks) / sizeof(breaks[0]); i++)
                if (breaks[i].armed && e->ExceptionCode == EXCEPTION_BREAKPOINT &&
                    e->ExceptionAddress == (void *)(uintptr_t)breaks[i].address) hit = &breaks[i];
            if (hit) {
                CONTEXT c;
                context(ev.dwThreadId, &c);
                SIZE_T n;
                WriteProcessMemory(process, (void *)(uintptr_t)hit->address, &hit->saved, 1, &n);
                FlushInstructionCache(process, (void *)(uintptr_t)hit->address, 1);
                c.Eip = hit->address;
                HANDLE thread = OpenThread(THREAD_ALL_ACCESS, FALSE, ev.dwThreadId);
                SetThreadContext(thread, &c);
                CloseHandle(thread);
                hit->armed = 0;
                if (hit->address == 0x3ee944) {
                    dump("stage1", 0x3f9000, 0x17000);
                    arm(1, 0xe9);
                } else if (hit->address == 0x3f94a4) {
                    dump("postfix", 0x400000, 0x50000);
                    arm(2, 0xff); arm(3, 0x83); arm(4, 0x56); arm(5, 0x5f); arm(6, 0x8b); arm(7, 0x55);
                } else if (hit->address == 0x40121f) {
                    char filename[1024] = {0};
                    ReadProcessMemory(process, (void *)(uintptr_t)word(c.Esp), filename, sizeof(filename) - 1, &n);
                    printf("CREATEFILE path=%s\n", filename);
                } else if (hit->address == 0x401225) {
                    printf("CREATEFILE_RETURN handle=%08lx last_error=%lu\n", c.Eax, word(main_teb + 0x34));
                } else if (hit->address == 0x401244) {
                    printf("READFILE_RETURN result=%lu bytes=%lu last_error=%lu\n", c.Eax, word(c.Esp + 8), word(main_teb + 0x34));
                } else if (hit->address == 0x4012e5) {
                    dump("samples", 0xf01070, 0x1000);
                    dump("synth-init", 0xb16b800, 0x600);
                } else if (hit->address == 0x405b46) {
                    printf("SAMPLE_NODE node=%08lx index=%lu length=%lu pointer=%08lx\n", c.Ecx, c.Edx,
                           word(0xf01070 + c.Edx * 4), word(0xf01870 + c.Edx * 4));
                }
            } else if (e->ExceptionCode == EXCEPTION_ACCESS_VIOLATION && !diagnosed) {
                CONTEXT c;
                context(ev.dwThreadId, &c);
                dump("fault-image", 0x3e0000, 0x220000);
                dump("fault-stack", c.Esp & ~0xfffUL, 0x5000);
                dump("fault-edx", c.Edx & ~0xfffUL, 0x10000);
                dump("fault-edi", c.Edi & ~0xfffUL, 0x10000);
                dump("fault-state", 0xb16b000, 0x12000);
                DWORD node = c.Edx;
                for (unsigned i = 0; node && i < 16; i++) {
                    DWORD fn = word(node + 0x10), param = word(node + 0x20);
                    printf("NODE address=%08lx function=%08lx parameter=%08lx value=%08lx samples=%08lx\n",
                           node, fn, param, word(param), word(node + 0xf0));
                    if (fn == 0x405b12) break;
                    node = word(node + 0x240);
                }
                diagnosed = 1;
                TerminateProcess(process, 5);
            } else if (e->ExceptionCode != EXCEPTION_BREAKPOINT) {
                disposition = DBG_EXCEPTION_NOT_HANDLED;
            }
        } else if (ev.dwDebugEventCode == EXIT_PROCESS_DEBUG_EVENT) {
            printf("EXIT code=%lu elapsed_ms=%lu\n", ev.u.ExitProcess.dwExitCode, GetTickCount() - start);
            ContinueDebugEvent(ev.dwProcessId, ev.dwThreadId, disposition);
            CloseHandle(pi.hThread);
            CloseHandle(process);
            return ev.u.ExitProcess.dwExitCode;
        }
        ContinueDebugEvent(ev.dwProcessId, ev.dwThreadId, disposition);
    }
}
