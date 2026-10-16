/* A safe post-loader rendezvous. Only Frida writes the injection trampoline. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdint.h>

static HANDLE child;
static void fail(const char *where) {
    fprintf(stderr,"A_LAUNCH_FAILURE %s error=%lu\n",where,GetLastError());
    if(child) TerminateProcess(child,125);
    ExitProcess(125);
}
int main(int argc,char **argv) {
    if(argc!=3) return 64;
    setvbuf(stdout,NULL,_IONBF,0);
    char command[2048]; snprintf(command,sizeof(command),"\"%s\"",argv[1]);
    STARTUPINFOA si={0}; PROCESS_INFORMATION pi={0}; si.cb=sizeof(si);
    if(!CreateProcessA(argv[1],command,NULL,NULL,FALSE,DEBUG_ONLY_THIS_PROCESS,NULL,NULL,&si,&pi)) fail("CreateProcess");
    child=pi.hProcess; CloseHandle(pi.hThread);
    DWORD start=GetTickCount(); int armed=0;
    for(;;) {
        DEBUG_EVENT e;
        if(!WaitForDebugEvent(&e,1000)) {
            if(GetLastError()==ERROR_SEM_TIMEOUT && GetTickCount()-start<290000) continue;
            fail("WaitForDebugEvent");
        }
        DWORD status=DBG_CONTINUE;
        if(e.dwDebugEventCode==CREATE_PROCESS_DEBUG_EVENT) {
            CONTEXT c={0}; c.ContextFlags=CONTEXT_DEBUG_REGISTERS; c.Dr0=0x406379; c.Dr7=1;
            if(!SetThreadContext(e.u.CreateProcessInfo.hThread,&c)) fail("SetThreadContext breakpoint");
            if(e.u.CreateProcessInfo.hFile) CloseHandle(e.u.CreateProcessInfo.hFile);
            CloseHandle(e.u.CreateProcessInfo.hThread); CloseHandle(e.u.CreateProcessInfo.hProcess);
        } else if(e.dwDebugEventCode==CREATE_THREAD_DEBUG_EVENT) CloseHandle(e.u.CreateThread.hThread);
        else if(e.dwDebugEventCode==LOAD_DLL_DEBUG_EVENT) {
            if(e.u.LoadDll.hFile) CloseHandle(e.u.LoadDll.hFile);
            printf("A_MODULE base=%p\n",e.u.LoadDll.lpBaseOfDll);
        } else if(e.dwDebugEventCode==EXCEPTION_DEBUG_EVENT) {
            DWORD code=e.u.Exception.ExceptionRecord.ExceptionCode;
            DWORD address=(DWORD)(uintptr_t)e.u.Exception.ExceptionRecord.ExceptionAddress;
            if(code==EXCEPTION_SINGLE_STEP && address==0x406379 && !armed) {
                HANDLE thread=OpenThread(THREAD_GET_CONTEXT|THREAD_SET_CONTEXT,FALSE,e.dwThreadId);
                CONTEXT c={0}; c.ContextFlags=CONTEXT_ALL;
                if(!thread || !GetThreadContext(thread,&c)) fail("GetThreadContext");
                c.Dr0=c.Dr6=c.Dr7=0; c.EFlags &= ~0x100; c.EFlags |= 0x10000;
                void *allocation=VirtualAllocEx(child,NULL,65536,MEM_COMMIT|MEM_RESERVE,PAGE_EXECUTE_READWRITE);
                if(!allocation) fail("VirtualAllocEx");
                /* Frida's injector needs a runnable host thread. A pending Wine
                 * debug event parks it in the server. Detach at this guarded
                 * pre-synth wait loop, preserving GPR/EFLAGS and touching no FP. */
                BYTE hold[]={0x9c,0x60,0xf3,0x90,0x81,0x3d,0,0,0,0,0x4b,0x4f,0x32,0x41,
                             0x75,0xf2,0x61,0x9d,0xe9,0,0,0,0};
                DWORD arena=(DWORD)(uintptr_t)allocation;
                memcpy(hold+6,&arena,4);
                DWORD delta=0x406379-(arena+0x2000+sizeof(hold));memcpy(hold+19,&delta,4);
                SIZE_T put=0;
                if(!WriteProcessMemory(child,(BYTE *)allocation+0x2000,hold,sizeof(hold),&put) || put!=sizeof(hold) ||
                   !FlushInstructionCache(child,(BYTE *)allocation+0x2000,sizeof(hold))) fail("runnable rendezvous");
                c.Eip=arena+0x2000;
                if(!SetThreadContext(thread,&c)) fail("set runnable rendezvous");
                CloseHandle(thread);
                if(!ContinueDebugEvent(e.dwProcessId,e.dwThreadId,DBG_CONTINUE) || !DebugActiveProcessStop(pi.dwProcessId))
                    fail("detach rendezvous debugger");
                printf("A_DEBUGGER_DETACHED site=0x00406379 wait=%p\n",(BYTE *)allocation+0x2000);
                FILE *file=fopen(argv[2],"wb"); if(!file) fail("rendezvous file");
                fprintf(file,"{\"windows_pid\":%lu,\"main_tid\":%lu,\"site\":%lu,\"allocation\":%lu}\n",
                        pi.dwProcessId,e.dwThreadId,address,(DWORD)(uintptr_t)allocation);
                fclose(file);
                printf("A_RENDEZVOUS pid=%lu tid=%lu allocation=%p\n",pi.dwProcessId,e.dwThreadId,allocation);
                DWORD state=0; SIZE_T got;
                for(unsigned i=0;i<600 && !state;i++) {
                    if(!ReadProcessMemory(child,allocation,&state,4,&got) || got!=4) fail("injection acknowledgment read");
                    if(!state) Sleep(100);
                }
                if(state!=0x41324f4b) fail("Frida injection missing or rejected");
                if(WaitForSingleObject(child,290000-(GetTickCount()-start))!=WAIT_OBJECT_0) fail("child bounded wait");
                DWORD result=125;if(!GetExitCodeProcess(child,&result)) fail("child exit code");
                printf("A_CHILD_EXIT code=%lu\n",result);CloseHandle(child);return (int)result;
            } else if(code==EXCEPTION_BREAKPOINT && !armed) {
                /* Initial loader breakpoint. */
            } else {
                status=DBG_EXCEPTION_NOT_HANDLED;
                if(!e.u.Exception.dwFirstChance || code==EXCEPTION_ACCESS_VIOLATION)
                    printf("A_EXCEPTION code=0x%08lx site=0x%08lx first=%lu\n",code,address,e.u.Exception.dwFirstChance);
            }
        } else if(e.dwDebugEventCode==EXIT_PROCESS_DEBUG_EVENT) {
            DWORD rc=e.u.ExitProcess.dwExitCode;
            printf("A_CHILD_EXIT code=%lu\n",rc);
            ContinueDebugEvent(e.dwProcessId,e.dwThreadId,DBG_CONTINUE); CloseHandle(child); return (int)rc;
        }
        if(!ContinueDebugEvent(e.dwProcessId,e.dwThreadId,status)) fail("ContinueDebugEvent");
    }
}
