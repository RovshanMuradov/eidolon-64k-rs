/* Run only through tools/wine-headless. Inject at the pinned PE entry before CRT/main. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <psapi.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static BYTE code[4096];static size_t used;
static void byte(BYTE n){code[used++]=n;}
static void word(DWORD n){memcpy(code+used,&n,4);used+=4;}
static void bytes(const BYTE *p,size_t n){memcpy(code+used,p,n);used+=n;}
static void mov(unsigned op,DWORD n){byte(op);word(n);}
static void call_iat(DWORD p){byte(0xff);byte(0x15);word(p);}
static void copy_regs(DWORD dest){bytes((BYTE[]){0x89,0xe6,0xfc},3);mov(0xbf,dest);mov(0xb9,9);bytes((BYTE[]){0xf3,0xa5},2);}
static void fx(unsigned op,DWORD dest){bytes((BYTE[]){0x0f,0xae,(BYTE)op},3);word(dest);}
static BYTE *raw;static IMAGE_NT_HEADERS32 *nt;
static void *at(DWORD rva){IMAGE_SECTION_HEADER *s=IMAGE_FIRST_SECTION(nt);for(unsigned i=0;i<nt->FileHeader.NumberOfSections;i++)if(rva>=s[i].VirtualAddress&&rva<s[i].VirtualAddress+s[i].SizeOfRawData)return raw+s[i].PointerToRawData+rva-s[i].VirtualAddress;return NULL;}
static DWORD iat(const char *name){IMAGE_IMPORT_DESCRIPTOR *d=at(nt->OptionalHeader.DataDirectory[1].VirtualAddress);for(;d->Name;d++){DWORD *o=at(d->OriginalFirstThunk);for(unsigned i=0;o[i];i++)if(!(o[i]&0x80000000)&&!strcmp((char*)at(o[i])+2,name))return d->FirstThunk+i*4;}return 0;}
static void save(const char *root,const char *name,const void *data,size_t n){char p[2300];snprintf(p,sizeof(p),"%s/%s",root,name);FILE*f=fopen(p,"wb");if(!f||fwrite(data,1,n,f)!=n)ExitProcess(124);fclose(f);}
int main(int argc,char **argv){
 if(argc!=4)return 64; /* target, helper, output */
 FILE*f=fopen(argv[1],"rb");if(!f)return 65;fseek(f,0,SEEK_END);long size=ftell(f);rewind(f);raw=malloc(size);if(fread(raw,1,size,f)!=(size_t)size)return 66;fclose(f);
 nt=(void*)(raw+((IMAGE_DOS_HEADER*)raw)->e_lfanew);if(nt->FileHeader.Machine!=0x14c||nt->OptionalHeader.AddressOfEntryPoint!=0x1460)return 67;
 SetEnvironmentVariableA("EIDOLON_RUST_OUTPUT",argv[3]);
 char cmd[2400];snprintf(cmd,sizeof(cmd),"\"%s\" --play",argv[1]);STARTUPINFOA si={0};si.cb=sizeof(si);PROCESS_INFORMATION pi={0};
 if(!CreateProcessA(argv[1],cmd,NULL,NULL,FALSE,CREATE_SUSPENDED,NULL,NULL,&si,&pi)){printf("CREATE_FAILED %lu\n",GetLastError());return 68;}
 CONTEXT c={0};c.ContextFlags=CONTEXT_FULL;DWORD base=0;SIZE_T n;
 if(!GetThreadContext(pi.hThread,&c)||!ReadProcessMemory(pi.hProcess,(void*)(uintptr_t)(c.Ebx+8),&base,4,&n))goto fail;
 DWORD entry=base+0x1460;BYTE original[10];if(!ReadProcessMemory(pi.hProcess,(void*)(uintptr_t)entry,original,10,&n))goto fail;
 if(original[0]!=0xc7||original[1]!=5||*(DWORD*)(original+2)!=base+0xb01b0||*(DWORD*)(original+6)!=0)goto fail;
 DWORD remote=(DWORD)(uintptr_t)VirtualAllocEx(pi.hProcess,NULL,8192,MEM_COMMIT|MEM_RESERVE,PAGE_EXECUTE_READWRITE);if(!remote)goto fail;
 DWORD proof=remote+4096, library=remote+2048, symbol=remote+3072;
 byte(0x9c);byte(0x60);bytes((BYTE[]){0x89,0xe5},2);copy_regs(proof);fx(5,proof+64);
 bytes((BYTE[]){0x83,0xe4,0xf0,0x83,0xec,0x0c},6);byte(0x68);word(library);call_iat(base+iat("LoadLibraryA"));bytes((BYTE[]){0x83,0xc4,0x0c,0x83,0xec,0x08},6);
 byte(0x68);word(symbol);byte(0x50);call_iat(base+iat("GetProcAddress"));bytes((BYTE[]){0x83,0xc4,0x08,0x83,0xec,0x0c},6);
 byte(0x68);word(proof);bytes((BYTE[]){0xff,0xd0,0x83,0xc4,0x10},5); /* cdecl capture_start */
 fx(0x0d,proof+64);bytes((BYTE[]){0x89,0xec,0x61,0x9d},4);
 char fault[32];if(GetEnvironmentVariableA("EIDOLON_ENTRY_FAULT",fault,sizeof(fault))){if(!strcmp(fault,"gpr"))bytes((BYTE[]){0x83,0xf0,0x01},3);else{DWORD changed=0x1fc0;WriteProcessMemory(pi.hProcess,(void*)(uintptr_t)(proof+1600),&changed,4,&n);fx(0x15,proof+1600);}}
 byte(0x9c);byte(0x60);copy_regs(proof+640);fx(5,proof+704);byte(0x61);byte(0x9d);
 byte(0xc7);byte(5);word(proof+1400);word(1);
 bytes(original,10);byte(0xe9);word(entry+10-(remote+used+4));
 memcpy(code+2048,argv[2],strlen(argv[2])+1);memcpy(code+3072,"capture_start",14);
 if(!WriteProcessMemory(pi.hProcess,(void*)(uintptr_t)remote,code,sizeof(code),&n))goto fail;
 DWORD old;BYTE jump[10]={0xe9};*(DWORD*)(jump+1)=remote-entry-5;memset(jump+5,0x90,5);
 if(!VirtualProtectEx(pi.hProcess,(void*)(uintptr_t)entry,10,PAGE_EXECUTE_READWRITE,&old)||!WriteProcessMemory(pi.hProcess,(void*)(uintptr_t)entry,jump,10,&n))goto fail;
 VirtualProtectEx(pi.hProcess,(void*)(uintptr_t)entry,10,old,&old);FlushInstructionCache(pi.hProcess,NULL,0);
 printf("SUSPENDED_BEFORE_ENTRY pid=%lu tid=%lu base=%08lx entry=%08lx stub=%08lx\n",pi.dwProcessId,pi.dwThreadId,base,entry,remote);fflush(stdout);
 ULONGLONG began=GetTickCount64();SIZE_T peak=0;ResumeThread(pi.hThread);int saved=0;
 while(WaitForSingleObject(pi.hProcess,100)==WAIT_TIMEOUT){PROCESS_MEMORY_COUNTERS memory={0};memory.cb=sizeof(memory);if(GetProcessMemoryInfo(pi.hProcess,&memory,sizeof(memory))&&memory.PeakWorkingSetSize>peak)peak=memory.PeakWorkingSetSize;DWORD ready=0;ReadProcessMemory(pi.hProcess,(void*)(uintptr_t)(proof+1400),&ready,4,&n);if(ready&&!saved){BYTE a[576],b[576];if(!ReadProcessMemory(pi.hProcess,(void*)(uintptr_t)proof,a,sizeof(a),&n)||!ReadProcessMemory(pi.hProcess,(void*)(uintptr_t)(proof+640),b,sizeof(b),&n))goto fail;save(argv[3],"entry-before.bin",a,sizeof(a));save(argv[3],"entry-after.bin",b,sizeof(b));saved=1;printf("ENTRY_PHYSICAL_EQUAL gpr=%d fp=%d\n",!memcmp(a,b,36),!memcmp(a+64,b+64,512));fflush(stdout);if(memcmp(a,b,36)||memcmp(a+64,b+64,512))goto fail;}}
 printf("CHILD_METRICS peak_working_set_bytes=%lu wall_ms=%llu\n",(DWORD)peak,GetTickCount64()-began);
 DWORD rc;GetExitCodeProcess(pi.hProcess,&rc);printf("CHILD_EXIT %lu entry_proof=%d\n",rc,saved);CloseHandle(pi.hThread);CloseHandle(pi.hProcess);return rc;
fail: printf("LAUNCH_FAILURE %lu\n",GetLastError());TerminateProcess(pi.hProcess,125);WaitForSingleObject(pi.hProcess,5000);return 125;
}
