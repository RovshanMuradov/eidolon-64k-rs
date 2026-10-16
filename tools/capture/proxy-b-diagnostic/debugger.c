/* D8 native debugger: inspect the synchronous driver-error breakpoint.
 * The original EXE and all Wine modules are unmodified on disk. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdint.h>

static HANDLE child;
static char folder[32768];
static void fail(const char *why) {
    printf("DEBUG_ERROR operation=%s error=%lu\n",why,GetLastError());
    if(child) TerminateProcess(child,125);
    ExitProcess(125);
}
static void save(const char *name,const void *bytes,DWORD length) {
    char path[32768];
    if(snprintf(path,sizeof(path),"%s/%s",folder,name)>=(int)sizeof(path)) fail("path");
    HANDLE file=CreateFileA(path,GENERIC_WRITE,FILE_SHARE_READ,NULL,CREATE_NEW,0,NULL);
    DWORD wrote;
    if(file==INVALID_HANDLE_VALUE || !WriteFile(file,bytes,length,&wrote,NULL) || wrote!=length)
        fail("save");
    FlushFileBuffers(file); CloseHandle(file);
}
int main(int argc,char **argv) {
    if(argc!=2) return 64;
    setvbuf(stdout,NULL,_IONBF,0);
    if(!GetEnvironmentVariableA("EIDOLON_B_OUTPUT",folder,sizeof(folder))) fail("output");
    STARTUPINFOA si={0}; PROCESS_INFORMATION pi={0}; si.cb=sizeof(si);
    char command[2048]; snprintf(command,sizeof(command),"\"%s\"",argv[1]);
    if(!CreateProcessA(argv[1],command,NULL,NULL,FALSE,DEBUG_ONLY_THIS_PROCESS,NULL,NULL,&si,&pi)) fail("CreateProcess");
    child=pi.hProcess; CloseHandle(pi.hThread);
    printf("DEBUG child_pid=%lu main_tid=%lu\n",pi.dwProcessId,pi.dwThreadId);
    BOOL initial=TRUE; unsigned captured=0;
    ULONGLONG started=GetTickCount64();
    for(;;) {
        DEBUG_EVENT e;
        if(!WaitForDebugEvent(&e,1000)) {
            if(GetLastError()==ERROR_SEM_TIMEOUT && GetTickCount64()-started<290000) continue;
            fail("WaitForDebugEvent");
        }
        DWORD status=DBG_CONTINUE;
        if(e.dwDebugEventCode==CREATE_PROCESS_DEBUG_EVENT) {
            CONTEXT c={0};c.ContextFlags=CONTEXT_DEBUG_REGISTERS;
            c.Dr0=0x4076a8;c.Dr1=0x4076aa;c.Dr2=0x406dcc;c.Dr3=0x406dce;c.Dr7=0x55;
            if(!SetThreadContext(e.u.CreateProcessInfo.hThread,&c)) fail("hardware_call_breakpoints");
            if(e.u.CreateProcessInfo.hFile) CloseHandle(e.u.CreateProcessInfo.hFile);
            CloseHandle(e.u.CreateProcessInfo.hThread); CloseHandle(e.u.CreateProcessInfo.hProcess);
        } else if(e.dwDebugEventCode==CREATE_THREAD_DEBUG_EVENT) CloseHandle(e.u.CreateThread.hThread);
        else if(e.dwDebugEventCode==LOAD_DLL_DEBUG_EVENT) {
            if(e.u.LoadDll.hFile) CloseHandle(e.u.LoadDll.hFile);
        } else if(e.dwDebugEventCode==EXCEPTION_DEBUG_EVENT) {
            DWORD code=e.u.Exception.ExceptionRecord.ExceptionCode;
            DWORD address=(DWORD)(uintptr_t)e.u.Exception.ExceptionRecord.ExceptionAddress;
            status=DBG_EXCEPTION_NOT_HANDLED;
            if(code==EXCEPTION_SINGLE_STEP && (address==0x4076a8 || address==0x4076aa || address==0x406dcc || address==0x406dce)) {
                HANDLE thread=OpenThread(THREAD_GET_CONTEXT|THREAD_SET_CONTEXT,FALSE,e.dwThreadId);
                CONTEXT c={0};c.ContextFlags=CONTEXT_ALL;
                if(!thread || !GetThreadContext(thread,&c)) fail("call_GetThreadContext");
                DWORD words[4];SIZE_T got;
                if(!ReadProcessMemory(child,(void *)(uintptr_t)c.Esp,words,sizeof(words),&got) || got!=sizeof(words)) fail("call_stack");
                printf("DEBUG hardware_pc=%08lx tid=%lu esp=%08lx eax=%08lx stack=%08lx,%08lx,%08lx,%08lx\n",address,e.dwThreadId,c.Esp,c.Eax,words[0],words[1],words[2],words[3]);
                if(address==0x406dcc) {
                    if(words[0]!=0x8b30 || !words[1] || words[1]>32) fail("shader_arguments");
                    DWORD pointers[32];
                    if(!ReadProcessMemory(child,(void *)(uintptr_t)words[2],pointers,words[1]*4,&got) || got!=words[1]*4) fail("shader_pointers");
                    for(DWORD i=0;i<words[1];++i) {
                        char text[65536];DWORD length=0;
                        for(;length<sizeof(text);++length) {
                            if(!ReadProcessMemory(child,(void *)(uintptr_t)(pointers[i]+length),text+length,1,&got) || got!=1) fail("shader_string");
                            if(!text[length]) break;
                        }
                        if(length==sizeof(text)) fail("shader_length");
                        char name[64];snprintf(name,sizeof(name),"program-source-%lu.glsl",i);save(name,text,length);
                        printf("DEBUG shader_source index=%lu pointer=%08lx bytes=%lu file=%s\n",i,pointers[i],length,name);
                    }
                } else if(address==0x406dce) {
                    printf("DEBUG shader_program=%lu\n",c.Eax);
                    c.Dr2=c.Dr3=0;c.Dr7=5;
                }
                c.Dr6=0;c.EFlags|=0x10000;
                if(!SetThreadContext(thread,&c)) fail("call_SetThreadContext");
                CloseHandle(thread);status=DBG_CONTINUE;
            } else if(code==EXCEPTION_BREAKPOINT && initial) {initial=FALSE;status=DBG_CONTINUE;}
            else if(code==EXCEPTION_BREAKPOINT && address!=0x401765) {
                HANDLE thread=OpenThread(THREAD_GET_CONTEXT,FALSE,e.dwThreadId);
                CONTEXT c={0}; c.ContextFlags=CONTEXT_ALL;
                if(!thread || !GetThreadContext(thread,&c)) fail("GetThreadContext");
                CloseHandle(thread);
                printf("DEBUG breakpoint=%08lx tid=%lu eip=%08lx esp=%08lx ebp=%08lx\n",address,e.dwThreadId,c.Eip,c.Esp,c.Ebp);
                MEMORY_BASIC_INFORMATION region;
                if(!VirtualQueryEx(child,(void *)(uintptr_t)c.Esp,&region,sizeof(region))) fail("VirtualQueryEx");
                DWORD length=(DWORD)(uintptr_t)region.BaseAddress+region.RegionSize-c.Esp;
                if(length>65536) length=65536;
                BYTE bytes[65536]; SIZE_T got;
                if(!ReadProcessMemory(child,(void *)(uintptr_t)c.Esp,bytes,length,&got) || got!=length) fail("stack_read");
                char name[64]; snprintf(name,sizeof(name),"debug-stack-%u.bin",captured);save(name,bytes,length);
                snprintf(name,sizeof(name),"debug-context-%u.bin",captured);save(name,&c,sizeof(c));
                printf("DEBUG stack_base=%08lx stack_bytes=%lu context_bytes=%u\n",c.Esp,length,(unsigned)sizeof(c));
                for(unsigned i=0;i+17*4<=length;i+=4) {
                    DWORD *words=(DWORD *)(bytes+i);
                    if(words[0]>=0x405f00 && words[0]<=0x408647) {
                        printf("DEBUG app_stack slot=%08lx",c.Esp+i);
                        for(unsigned j=0;j<17;j++) printf(" %08lx",words[j]);
                        puts("");
                    }
                }
                captured++;status=DBG_CONTINUE;
            }
        } else if(e.dwDebugEventCode==EXIT_PROCESS_DEBUG_EVENT) {
            DWORD code=e.u.ExitProcess.dwExitCode;
            printf("DEBUG child_exit=%lu error_breakpoints=%u\n",code,captured);
            ContinueDebugEvent(e.dwProcessId,e.dwThreadId,DBG_CONTINUE);
            CloseHandle(child);return code;
        }
        if(!ContinueDebugEvent(e.dwProcessId,e.dwThreadId,status)) fail("ContinueDebugEvent");
    }
}
