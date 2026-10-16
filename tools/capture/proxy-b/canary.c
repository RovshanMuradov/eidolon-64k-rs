/* Run only through tools/wine-headless. Exit 125 means G1a rejected. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdint.h>

int main(void) {
    const char *names[] = {"opengl32.dll", "winmm.dll"};
    int result = 0;
    setvbuf(stdout, NULL, _IONBF, 0);
    for (unsigned i = 0; i < 2; ++i) {
        HMODULE module = LoadLibraryA(names[i]);
        FARPROC proc = module ? GetProcAddress(module, "EidolonProbeBackend") : NULL;
        printf("G1A_CANARY dll=%s module=%p probe=%p error=%lu\n",
               names[i], (void *)module, (void *)(uintptr_t)proc, GetLastError());
        if (!proc) { result = 125; continue; }
        DWORD status = ((DWORD (WINAPI *)(void))(uintptr_t)proc)();
        printf("G1A_CANARY dll=%s status=%lu\n", names[i], status);
        if (status) result = 125;
    }
    printf("G1A_CANARY exit=%d\n", result);
    return result;
}
