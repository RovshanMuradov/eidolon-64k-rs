/* Read-only observations apart from restored one-shot debug breakpoints.
 * No clock/RNG substitution, framebuffer readback or PCM capture. PE32 only. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <mmsystem.h>
#include <stdio.h>
#include <stdint.h>
#include <math.h>

static HANDLE child;
static ULONGLONG start;
static unsigned swaps, swap_failures, next_second;
static DWORD synth_tid, synth_done, main_tid, write_tick;
static int armed;
typedef struct { DWORD address; BYTE original; int active; const char *name; } Break;
static Break points[] = {
    {0x40121f,0,0,"bank_open_call"}, {0x401225,0,0,"bank_open_return"},
    {0x401244,0,0,"bank_read_return"}, {0x4012e5,0,0,"bank_loaded"},
    {0x401636,0,0,"synth_entry"}, {0x401765,0,0,"synth_complete"},
    {0x407ae9,0,0,"wave_open_call"}, {0x407aef,0,0,"wave_open_return"},
    {0x407b03,0,0,"wave_prepare_return"}, {0x407b12,0,0,"wave_write_return"},
    {0x407b97,0,0,"first_position_return"}, {0x4085fd,0,0,"first_timeline_swap"},
    {0x408618,0,0,"native_exit_call"}
};

static void fail(const char *operation) {
    fprintf(stderr,"DIAG_ERROR operation=%s error=%lu\n",operation,GetLastError());
    if (child) TerminateProcess(child, 125);
    ExitProcess(125);
}
static void read_at(DWORD address, void *out, SIZE_T length) {
    SIZE_T got = 0;
    if (!ReadProcessMemory(child,(void *)(uintptr_t)address,out,length,&got) || got != length)
        fail("ReadProcessMemory");
}
static DWORD u32(DWORD address) { DWORD value; read_at(address,&value,4); return value; }
static void write_byte(DWORD address, BYTE byte) {
    SIZE_T got = 0;
    if (!WriteProcessMemory(child,(void *)(uintptr_t)address,&byte,1,&got) || got != 1)
        fail("WriteProcessMemory");
    if (!FlushInstructionCache(child,(void *)(uintptr_t)address,1)) fail("FlushInstructionCache");
}
static void prefix(const char *name) {
    printf("DIAG t_ms=%llu event=%s",GetTickCount64()-start,name);
}
static void pcm_probe(void) {
    /* Eight 512-frame windows at submission; synthesis can still be writing. */
    DWORD buffer=u32(0x43edd0), length=u32(0x43edd4);
    unsigned nonzero=0, nonfinite=0, count=0;
    double sumsq=0, peak=0;
    if (length != 159716352) fail("unexpected PCM length");
    for (unsigned window=0;window<8;window++) {
        float data[1024];
        DWORD offset=(DWORD)(((uint64_t)(length-sizeof(data))*window/7)/8*8);
        read_at(buffer+offset,data,sizeof(data));
        for(unsigned i=0;i<1024;i++) {
            double value=data[i];
            count++;
            if(!isfinite(value)) { nonfinite++; continue; }
            if(value != 0) nonzero++;
            sumsq+=value*value;
            if(fabs(value)>peak) peak=fabs(value);
        }
    }
    printf(" pcm_probe_floats=%u nonzero=%u nonfinite=%u rms=%.9g peak=%.9g",count,nonzero,nonfinite,sqrt(sumsq/count),peak);
}
static void observe(Break *point, CONTEXT *c, DWORD tid) {
    prefix(point->name);
    printf(" tid=%lu address=0x%08lx eax=0x%08lx",tid,point->address,c->Eax);
    switch(point->address) {
    case 0x40121f: {
        char path[260]={0}; read_at(u32(c->Esp),path,259); printf(" path=%s",path); break;
    }
    case 0x401244: printf(" bytes_read=%lu",u32(c->Esp+8)); break;
    case 0x4012e5:
        printf(" sample127_bytes=%lu sample127_pointer=0x%08lx",u32(0xf01070+4*127),u32(0xf01870+4*127)); break;
    case 0x401636: synth_tid=tid; printf(" buffer=0x%08lx",u32(c->Esp+4)); break;
    case 0x401765:
        synth_done=1; printf(" generated_frames=%lu",u32(0xb16bd20)); break;
    case 0x407ae9: {
        WAVEFORMATEX f; read_at(0x43702c,&f,sizeof(f));
        printf(" tag=%u channels=%u hz=%lu bits=%u align=%u",f.wFormatTag,f.nChannels,f.nSamplesPerSec,f.wBitsPerSample,f.nBlockAlign); break;
    }
    case 0x407b12:
        write_tick=GetTickCount();
        printf(" buffer=0x%08lx bytes=%lu synth_done=%lu header_flags=0x%08lx",u32(0x43edd0),u32(0x43edd4),synth_done,u32(0x43ede0));
        pcm_probe(); break;
    case 0x407b97:
        printf(" mmtime_type=%lu sample_position=%lu",u32(0x437020),u32(0x437024)); break;
    case 0x4085fd:
        printf(" width=%lu height=%lu hdc=0x%08lx",u32(0xb17bf2c),u32(0xb17bfac),u32(c->Esp));
        c->Dr0=0x408603; c->Dr7=1; c->Dr6=0; break;
    case 0x408618: {
        float seconds; read_at(c->Ebp-0x34,&seconds,4);
        printf(" exit_argument=%lu sample_position=%lu mmtime_type=%lu seconds=%.9g swaps=%u swap_failures=%u elapsed_since_write_ms=%lu synth_done=%lu",
            u32(c->Esp),u32(0x437024),u32(0x437020),seconds,swaps,swap_failures,GetTickCount()-write_tick,synth_done);
        break;
    }
    }
    puts("");
}
int main(int argc,char **argv) {
    if(argc!=2) { fprintf(stderr,"usage: diagnose-playback.exe native.exe\n"); return 64; }
    setvbuf(stdout,NULL,_IONBF,0);
    char command[2048]; snprintf(command,sizeof(command),"\"%s\"",argv[1]);
    STARTUPINFOA si={0}; PROCESS_INFORMATION pi={0}; si.cb=sizeof(si);
    start=GetTickCount64();
    if(!CreateProcessA(argv[1],command,NULL,NULL,FALSE,DEBUG_ONLY_THIS_PROCESS,NULL,NULL,&si,&pi)) fail("CreateProcess");
    child=pi.hProcess; main_tid=pi.dwThreadId;
    CloseHandle(pi.hThread);
    prefix("child_created"); printf(" pid=%lu main_tid=%lu\n",pi.dwProcessId,main_tid);
    for(;;) {
        DEBUG_EVENT e;
        if(!WaitForDebugEvent(&e,1000)) {
            if(GetLastError()==ERROR_SEM_TIMEOUT && GetTickCount64()-start<580000) continue;
            fail("WaitForDebugEvent");
        }
        DWORD status=DBG_CONTINUE;
        if(e.dwDebugEventCode==CREATE_PROCESS_DEBUG_EVENT) {
            CONTEXT c={0}; c.ContextFlags=CONTEXT_DEBUG_REGISTERS;
            c.Dr0=0x406379; c.Dr7=1;
            if(!SetThreadContext(e.u.CreateProcessInfo.hThread,&c)) fail("initial hardware breakpoint");
            if(e.u.CreateProcessInfo.hFile) CloseHandle(e.u.CreateProcessInfo.hFile);
            CloseHandle(e.u.CreateProcessInfo.hThread);
            CloseHandle(e.u.CreateProcessInfo.hProcess);
        } else if(e.dwDebugEventCode==CREATE_THREAD_DEBUG_EVENT) {
            CloseHandle(e.u.CreateThread.hThread);
        } else if(e.dwDebugEventCode==LOAD_DLL_DEBUG_EVENT) {
            if(e.u.LoadDll.hFile) CloseHandle(e.u.LoadDll.hFile);
        } else if(e.dwDebugEventCode==EXIT_THREAD_DEBUG_EVENT && e.dwThreadId==synth_tid) {
            prefix("synth_thread_exit"); printf(" tid=%lu code=%lu\n",e.dwThreadId,e.u.ExitThread.dwExitCode);
        } else if(e.dwDebugEventCode==EXCEPTION_DEBUG_EVENT) {
            DWORD code=e.u.Exception.ExceptionRecord.ExceptionCode;
            DWORD address=(DWORD)(uintptr_t)e.u.Exception.ExceptionRecord.ExceptionAddress;
            HANDLE thread=OpenThread(THREAD_GET_CONTEXT|THREAD_SET_CONTEXT,FALSE,e.dwThreadId);
            if(!thread) fail("OpenThread");
            CONTEXT c={0}; c.ContextFlags=CONTEXT_ALL;
            if(!GetThreadContext(thread,&c)) fail("GetThreadContext");
            int handled=0;
            if(code==EXCEPTION_SINGLE_STEP && address==0x406379 && !armed) {
                c.Dr0=c.Dr6=c.Dr7=0; c.EFlags|=0x10000;
                for(unsigned i=0;i<sizeof(points)/sizeof(*points);i++) {
                    read_at(points[i].address,&points[i].original,1);
                    write_byte(points[i].address,0xcc); points[i].active=1;
                }
                armed=1; handled=1; prefix("application_entry"); puts(" hooks_armed=13");
            } else if(code==EXCEPTION_SINGLE_STEP && address==0x408603 && e.dwThreadId==main_tid) {
                swaps++; if(!c.Eax) swap_failures++;
                DWORD samples=u32(0x437024);
                if(samples/44100>=next_second) {
                    prefix("timeline_progress"); printf(" swaps=%u swap_failures=%u samples=%lu seconds=%.6f\n",swaps,swap_failures,samples,samples/44100.0);
                    next_second=samples/44100+30;
                }
                c.Dr6=0; c.EFlags|=0x10000; handled=1;
            } else if(code==EXCEPTION_BREAKPOINT) {
                for(unsigned i=0;i<sizeof(points)/sizeof(*points);i++) {
                    if(points[i].active && points[i].address==address) {
                        write_byte(address,points[i].original); points[i].active=0;
                        c.Eip=address; observe(&points[i],&c,e.dwThreadId); handled=1; break;
                    }
                }
                if(!armed) handled=1; /* Windows loader's initial breakpoint. */
            }
            if(handled) {
                if(!SetThreadContext(thread,&c)) fail("SetThreadContext");
            } else {
                status=DBG_EXCEPTION_NOT_HANDLED;
                if(!e.u.Exception.dwFirstChance || code==EXCEPTION_ACCESS_VIOLATION) {
                    prefix("exception"); printf(" code=0x%08lx address=0x%08lx first_chance=%lu\n",code,address,e.u.Exception.dwFirstChance);
                }
            }
            CloseHandle(thread);
        } else if(e.dwDebugEventCode==EXIT_PROCESS_DEBUG_EVENT) {
            DWORD result=e.u.ExitProcess.dwExitCode;
            prefix("child_exit"); printf(" code=%lu swaps=%u swap_failures=%u\n",result,swaps,swap_failures);
            ContinueDebugEvent(e.dwProcessId,e.dwThreadId,DBG_CONTINUE);
            CloseHandle(child);
            return (int)result;
        }
        if(!ContinueDebugEvent(e.dwProcessId,e.dwThreadId,status)) fail("ContinueDebugEvent");
    }
}
