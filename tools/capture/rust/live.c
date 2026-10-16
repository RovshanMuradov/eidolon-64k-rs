/* Native injected adapter. capture.c supplies synchronous final-buffer/file primitives. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <mmsystem.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>
DWORD __cdecl capture_init(const char*,const unsigned char*);
DWORD __cdecl capture_event(DWORD,const unsigned char*,DWORD);
DWORD __cdecl capture_cursor(void);
void marker_hook(void);void *marker_trampoline;
void position_gate(void);
void semantic_arm(BYTE*,const char*);void semantic_marker(DWORD,const BYTE*,DWORD*);
static MMRESULT (WINAPI *real_position)(HWAVEOUT,LPMMTIME,UINT);
static DWORD stop_frames=3,calls;static char output[2048];static int fault,full_mode;static BYTE first_fp[512],expected_gpr[36];
static ULONGLONG started;
static int position_fault;static unsigned position_calls;
static BYTE position_expected[36];
static void save(const char *name,const void *data,size_t n){char path[2304];snprintf(path,sizeof(path),"%s/%s",output,name);FILE*f=fopen(path,"wb");if(!f||fwrite(data,1,n,f)!=n)ExitProcess(125);fclose(f);}
MMRESULT WINAPI position_body(HWAVEOUT h,LPMMTIME t,UINT n){
 BYTE fp[512] __attribute__((aligned(16)))={0},after[512] __attribute__((aligned(16)))={0};__asm__ __volatile__("fxsave %0":"=m"(fp));
 MMRESULT rc=real_position(h,t,n);if(rc||n!=12||t->wType!=TIME_SAMPLES)ExitProcess(125);t->u.sample=capture_cursor();
 __asm__ __volatile__("fxrstor %0"::"m"(fp));
 if(position_fault&&!position_calls){DWORD changed=*(DWORD*)(fp+24)^0x40;__asm__ __volatile__("ldmxcsr %0"::"m"(changed));}
 __asm__ __volatile__("fxsave %0":"=m"(after));
 if(!position_calls){save("position-before-fx.bin",fp,512);save("position-after-fx.bin",after,512);}
 if(memcmp(fp,after,512)){printf("POSITION_FP_MISMATCH\n");fflush(stdout);ExitProcess(125);}
 position_calls++;__asm__ __volatile__("fxrstor %0"::"m"(fp));return rc;
}
void position_begin(BYTE *registers){memcpy(position_expected,registers,36);}
void position_check_gpr(BYTE *after){
 /* EAX is the documented MMRESULT return value; all other registers/flags are preserved by the gate. */
 if(memcmp(position_expected,after,28)||memcmp(position_expected+32,after+32,4)){printf("POSITION_GPR_MISMATCH\n");fflush(stdout);ExitProcess(125);}
 if(position_calls==1){save("position-before-gpr.bin",position_expected,36);save("position-after-gpr.bin",after,36);}
}
void marker_observe(DWORD *stack,BYTE *fp){
 DWORD *args=(DWORD*)(uintptr_t)(stack[3]+4); /* PUSHAD saved ESP points at saved EFLAGS. */
 DWORD kind=args[1],count=args[3];const BYTE *payload=(void*)(uintptr_t)args[2];
 if(kind==6||kind==1||kind==5){printf("RUNTIME_TIMING kind=%lu elapsed_ms=%llu\n",kind,GetTickCount64()-started);fflush(stdout);}
 memcpy(expected_gpr,stack,36);
 if(calls==0){memcpy(first_fp,fp,512);save("marker-before-gpr.bin",stack,36);save("marker-before-fx.bin",fp,512);}
 semantic_marker(kind,payload,stack);
 DWORD rc=capture_event(kind,payload,count);
 printf("CAPTURE_EVENT kind=%lu bytes=%lu cursor=%lu rc=%lu\n",kind,count,capture_cursor(),rc);fflush(stdout);
 if(rc)ExitProcess(125);
 if(fault==1 && calls==0)fp[24]^=0x40;
 if(fault==2 && calls==0)stack[7]^=1;
 calls++;
 if(!full_mode && kind==4 && capture_cursor()/735>=stop_frames){printf("PLANNED_SHORT_STOP frames=%lu\n",stop_frames);fflush(stdout);ExitProcess(0);}
}
void marker_check_fp(BYTE *before,BYTE *after){if(memcmp(before,after,512)||(calls==1&&memcmp(first_fp,after,512))){save("marker-rejected-fx.bin",after,512);printf("HOOK_FP_MISMATCH\n");fflush(stdout);ExitProcess(125);}if(calls==1){save("marker-restored-fx.bin",after,512);printf("HOOK_FP_EQUAL\n");fflush(stdout);}}
void marker_check_gpr(BYTE *after){if(memcmp(expected_gpr,after,36)){save("marker-rejected-gpr.bin",after,36);printf("HOOK_GPR_MISMATCH\n");fflush(stdout);ExitProcess(125);}if(calls==1){save("marker-restored-gpr.bin",after,36);printf("HOOK_GPR_EQUAL\n");fflush(stdout);}}
static void **find_iat(BYTE *base,const char *wanted){IMAGE_NT_HEADERS32 *nt=(void*)(base+((IMAGE_DOS_HEADER*)base)->e_lfanew);IMAGE_IMPORT_DESCRIPTOR *d=(void*)(base+nt->OptionalHeader.DataDirectory[1].VirtualAddress);for(;d->Name;d++){DWORD*names=(void*)(base+d->OriginalFirstThunk);void **slots=(void*)(base+d->FirstThunk);for(unsigned i=0;names[i];i++)if(!(names[i]&0x80000000)&&!strcmp((char*)(base+names[i]+2),wanted))return slots+i;}return NULL;}
__declspec(dllexport) DWORD __cdecl capture_start(void *proof){
 started=GetTickCount64();
 (void)proof;BYTE *base=(void*)GetModuleHandleA(NULL);BYTE *marker=(void*)GetProcAddress((HMODULE)base,"eidolon_runtime_event");
 const BYTE expected[]={0x55,0x89,0xe5,0x56,0x83,0xec,0x0c};
 if(!marker||memcmp(marker,expected,7))ExitProcess(125);
 if(!GetEnvironmentVariableA("EIDOLON_RUST_OUTPUT",output,sizeof(output)))ExitProcess(125);
 char text[32];if(GetEnvironmentVariableA("EIDOLON_RUST_FRAMES",text,sizeof(text)))stop_frames=strtoul(text,NULL,10);
 full_mode=GetEnvironmentVariableA("EIDOLON_RUST_FULL",text,sizeof(text))!=0;
 position_fault=GetEnvironmentVariableA("EIDOLON_RUST_POSITION_FAULT",text,sizeof(text))!=0;
 if(GetEnvironmentVariableA("EIDOLON_RUST_FAULT",text,sizeof(text)))fault=!strcmp(text,"gpr")?2:1;
 unsigned char keep[27000]={0};
 if(full_mode&&!GetEnvironmentVariableA("EIDOLON_RUST_SEMANTIC",text,sizeof(text))){char path[2304];if(stop_frames!=27000||!GetEnvironmentVariableA("EIDOLON_RUST_KEEP",path,sizeof(path)))ExitProcess(125);FILE*f=fopen(path,"rb");if(!f||fread(keep,1,sizeof(keep),f)!=sizeof(keep)||fgetc(f)!=EOF)ExitProcess(125);fclose(f);unsigned count=0;for(unsigned i=0;i<27000;i++)count+=keep[i]!=0;if(count!=510)ExitProcess(125);}
 else for(unsigned i=0;i<stop_frames&&i<27000;i++)keep[i]=1;
 if(capture_init(output,keep))ExitProcess(125);
 semantic_arm(base,output);
 marker_trampoline=VirtualAlloc(NULL,32,MEM_COMMIT|MEM_RESERVE,PAGE_EXECUTE_READWRITE);if(!marker_trampoline)ExitProcess(125);
 BYTE *tramp=marker_trampoline;memcpy(tramp,expected,7);tramp[7]=0xe9;*(DWORD*)(tramp+8)=(DWORD)(uintptr_t)(marker+7)-(DWORD)(uintptr_t)(tramp+12);
 DWORD old;VirtualProtect(marker,7,PAGE_EXECUTE_READWRITE,&old);marker[0]=0xe9;*(DWORD*)(marker+1)=(DWORD)(uintptr_t)marker_hook-(DWORD)(uintptr_t)(marker+5);marker[5]=marker[6]=0x90;VirtualProtect(marker,7,old,&old);
 void **slot=find_iat(base,"waveOutGetPosition");if(!slot)ExitProcess(125);real_position=(void*)*slot;VirtualProtect(slot,4,PAGE_READWRITE,&old);*slot=position_gate;VirtualProtect(slot,4,old,&old);
 FlushInstructionCache(GetCurrentProcess(),NULL,0);
 printf("NATIVE_ADAPTER_ARMED base=%p marker=%p iat=%p frames=%lu\n",base,marker,slot,stop_frames);fflush(stdout);return 0;
}
