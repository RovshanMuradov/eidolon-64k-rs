/* D28 observed fields only. Private offsets are pinned to the immutable PE. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <GL/gl.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
void seed_gate(void),draw_gate(void);void *seed_trampoline,*real_rect;
static BYTE *image;static char folder[2048];static int active,enabled,seed_seen,seed_fault;static DWORD frame,ordinal;
static BYTE seed_gpr[36],seed_fp[512],draw_gpr[36];static unsigned draw_calls;
static FILE *uniform_file,*program_file,*object_file;
static PROC (WINAPI *lookup)(LPCSTR);
static GLuint (APIENTRY *create_program)(GLenum,GLsizei,const char*const*);
static void (APIENTRY *gen_fbos)(GLsizei,GLuint*), (APIENTRY *gen_textures)(GLsizei,GLuint*);
static GLint (APIENTRY *location)(GLuint,const char*);
static void (APIENTRY *uniform_i)(GLuint,GLint,GLint*), (APIENTRY *uniform_f)(GLuint,GLint,GLfloat*), (APIENTRY *active_texture)(GLenum);
static void fail(const char*s){printf("SEMANTIC_FAILURE %s\n",s);fflush(stdout);ExitProcess(125);}
static FILE *open_file(const char*name){char path[2304];snprintf(path,sizeof(path),"%s/%s",folder,name);FILE*f=fopen(path,"wb");if(!f)fail("file open");return f;}
static void write_bytes(FILE*f,const void*p,size_t n){if(fwrite(p,1,n,f)!=n)fail("file write");}
static void save(const char*name,const void*p,size_t n){FILE*f=open_file(name);write_bytes(f,p,n);fclose(f);}
#include "curves.c"
static void **iat(const char*name){IMAGE_NT_HEADERS32*n=(void*)(image+((IMAGE_DOS_HEADER*)image)->e_lfanew);IMAGE_IMPORT_DESCRIPTOR*d=(void*)(image+n->OptionalHeader.DataDirectory[1].VirtualAddress);for(;d->Name;d++){DWORD*names=(void*)(image+d->OriginalFirstThunk);void**slots=(void*)(image+d->FirstThunk);for(unsigned i=0;names[i];i++)if(!(names[i]&0x80000000)&&!strcmp((char*)(image+names[i]+2),name))return slots+i;}fail("IAT name");return NULL;}
static void *route(const char*name,void*replacement){void**slot=iat(name);void*old=*slot;DWORD protect;if(!VirtualProtect(slot,4,PAGE_READWRITE,&protect))fail("IAT protect");*slot=replacement;VirtualProtect(slot,4,protect,&protect);return old;}
static GLuint APIENTRY program(GLenum type,GLsizei count,const char*const*strings){
 GLuint id=create_program(type,count,strings);BYTE fp[512] __attribute__((aligned(16)));__asm__ __volatile__("fxsave %0":"=m"(fp));
 DWORD h[3]={id,type,count};write_bytes(program_file,h,sizeof(h));for(int i=0;i<count;i++){DWORD n=strlen(strings[i])+1;write_bytes(program_file,&n,4);write_bytes(program_file,strings[i],n);}fflush(program_file);
 __asm__ __volatile__("fxrstor %0"::"m"(fp));return id;
}
static void objects(DWORD kind,GLsizei count,GLuint*ids){DWORD h[2]={kind,count};write_bytes(object_file,h,8);write_bytes(object_file,ids,count*4);fflush(object_file);}
static void APIENTRY framebuffers(GLsizei count,GLuint*ids){gen_fbos(count,ids);BYTE fp[512] __attribute__((aligned(16)));__asm__ __volatile__("fxsave %0":"=m"(fp));objects(1,count,ids);__asm__ __volatile__("fxrstor %0"::"m"(fp));}
static void APIENTRY textures(GLsizei count,GLuint*ids){gen_textures(count,ids);BYTE fp[512] __attribute__((aligned(16)));__asm__ __volatile__("fxsave %0":"=m"(fp));objects(2,count,ids);__asm__ __volatile__("fxrstor %0"::"m"(fp));}
static PROC WINAPI resolver(LPCSTR name){PROC p=lookup(name);if(!strcmp(name,"glCreateShaderProgramv")){create_program=(void*)p;return (PROC)(void*)program;}if(!strcmp(name,"glGenFramebuffers")){gen_fbos=(void*)p;return (PROC)(void*)framebuffers;}return p;}
void seed_observe(DWORD*s,BYTE*fp){
 if(seed_seen++)fail("duplicate seed");
 memcpy(seed_gpr,s,36);memcpy(seed_fp,fp,512);
 BYTE*r=(void*)(uintptr_t)s[1];BYTE*state=*(BYTE**)(r+0x168c);if(state!=*(BYTE**)(r+0x1410))fail("state aliases");
 DWORD h[5]={(DWORD)(uintptr_t)image,0xa3b5,(DWORD)(uintptr_t)r,(DWORD)(uintptr_t)state,GetCurrentThreadId()};
 save("seed-phase.bin",h,sizeof(h));save("ready-seed.bin",r+0x1400,16);save("ready-tick.bin",state,4);save("seed-before-gpr.bin",s,36);save("seed-before-fx.bin",fp,512);
 if(seed_fault)fp[24]^=0x40;
}
void seed_check_fp(BYTE*before,BYTE*after){if(memcmp(before,after,512)||memcmp(seed_fp,after,512)){save("seed-rejected-fx.bin",after,512);fail("seed physical FP");}save("seed-after-fx.bin",after,512);}
void seed_check_gpr(BYTE*after){if(memcmp(seed_gpr,after,36))fail("seed physical GPR");save("seed-after-gpr.bin",after,36);}
void draw_observe(DWORD*s,BYTE*fp){
 memcpy(draw_gpr,s,36);if(!active)return;
 DWORD ret=*(DWORD*)(uintptr_t)(s[3]+4);if(ret!=(DWORD)(uintptr_t)image+0x143d5)fail("draw caller");
 if(!location){location=(void*)lookup("glGetUniformLocation");uniform_i=(void*)lookup("glGetUniformiv");uniform_f=(void*)lookup("glGetUniformfv");active_texture=(void*)lookup("glActiveTexture");if(!location||!uniform_i||!uniform_f||!active_texture)fail("query functions");}
 if(!draw_calls){save("draw-before-gpr.bin",s,36);save("draw-before-fx.bin",fp,512);}
 if(curves_only){curve_draw(ret,ordinal++);draw_calls++;return;}
 DWORD record[19]={frame,ordinal++};GLint prog,fbo,viewport[4],before,after,unit=-1,tex=0;GLfloat time[4]={0};
 GLenum error=glGetError();if(error)fail("preexisting draw GL error");
 glGetIntegerv(0x8b8d,&prog);glGetIntegerv(0x8ca6,&fbo);glGetIntegerv(GL_VIEWPORT,viewport);glGetIntegerv(0x84e0,&before);
 GLint t=location(prog,"uTimeResolution"),c=location(prog,"uClouds");if(t>=0)uniform_f(prog,t,time);
 if(c>=0){uniform_i(prog,c,&unit);if(unit<0||unit>=32)fail("sampler unit");active_texture(0x84c0+unit);glGetIntegerv(0x806a,&tex);active_texture(before);}
 glGetIntegerv(0x84e0,&after);if(before!=after||glGetError())fail("draw GL restoration");
 record[2]=prog;record[3]=fbo;memcpy(record+4,viewport,16);record[8]=t;memcpy(record+9,time,12);record[12]=c;record[13]=unit;record[14]=tex;record[15]=before;record[16]=after;record[17]=error;record[18]=0;
 write_bytes(uniform_file,record,sizeof(record));draw_calls++;
}
void draw_check_fp(BYTE*before,BYTE*after){if(memcmp(before,after,512))fail("draw physical FP");if(draw_calls==1)save("draw-after-fx.bin",after,512);}
void draw_check_gpr(BYTE*after){if(memcmp(draw_gpr,after,36))fail("draw physical GPR");if(draw_calls==1)save("draw-after-gpr.bin",after,36);}
void semantic_marker(DWORD kind,const BYTE*payload,DWORD*s){
 if(!enabled)return;
 if(kind==1){DWORD ret=*(DWORD*)(uintptr_t)(s[3]+4);BYTE*ebp=(void*)(uintptr_t)s[2];if(ret!=(DWORD)(uintptr_t)image+0x12a09||memcmp(ebp-0x670,payload+28,256))fail("previous phase attribution");save("previous-seconds.bin",ebp-0x570,4);save("initial-physics-live.bin",ebp-0x670,256);DWORD h[3]={ret,(DWORD)(uintptr_t)ebp,GetCurrentThreadId()};save("previous-phase.bin",h,sizeof(h));}
 if(kind==2){if(active)fail("draw phase overlap");frame=*(DWORD*)payload;ordinal=0;active=1;}
 if(kind==3){if(!active||ordinal!=19)fail("draw coverage");active=0;fflush(uniform_file);}
}
void semantic_arm(BYTE*base,const char*output){
 char mode[32];if(!GetEnvironmentVariableA("EIDOLON_RUST_SEMANTIC",mode,sizeof(mode)))return;enabled=1;image=base;strcpy(folder,output);
 seed_fault=GetEnvironmentVariableA("EIDOLON_SEED_FAULT",mode,sizeof(mode))!=0;
 uniform_file=open_file("uniforms.bin");program_file=open_file("programs.bin");object_file=open_file("objects.bin");
 char samples[2304];if(GetEnvironmentVariableA("EIDOLON_CURVE_SAMPLES",samples,sizeof(samples))){FILE*f=fopen(samples,"rb");if(!f||fread(curve_samples,1,27000,f)!=27000||fgetc(f)!=EOF)fail("curve sample mask");fclose(f);curves_only=1;curve_file=open_file("curves.bin");}
 BYTE*site=base+0xa3b5;const BYTE expected[]={0x8b,0x5c,0x24,0x18,0x31,0xff,0x89,0x30,0xbe,0,0x0d,0,0};if(memcmp(site,expected,sizeof(expected)))fail("seed fingerprint");
 BYTE*t=VirtualAlloc(NULL,32,MEM_COMMIT|MEM_RESERVE,PAGE_EXECUTE_READWRITE);if(!t)fail("seed trampoline");seed_trampoline=t;memcpy(t,site,6);t[6]=0xe9;*(DWORD*)(t+7)=(DWORD)(uintptr_t)(site+6)-(DWORD)(uintptr_t)(t+11);
 DWORD protect;if(!VirtualProtect(site,6,PAGE_EXECUTE_READWRITE,&protect))fail("seed protect");site[0]=0xe9;*(DWORD*)(site+1)=(DWORD)(uintptr_t)seed_gate-(DWORD)(uintptr_t)(site+5);site[5]=0x90;VirtualProtect(site,6,protect,&protect);
 lookup=route("wglGetProcAddress",resolver);real_rect=route("glRecti",draw_gate);gen_textures=route("glGenTextures",textures);FlushInstructionCache(GetCurrentProcess(),NULL,0);
}
