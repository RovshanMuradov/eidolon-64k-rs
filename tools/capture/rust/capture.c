/* Synchronous capture helper; target execution/ABI restoration is not yet validated. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <wincrypt.h>
#include <GL/gl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define PCM_BYTES 159716352u
#define PIXELS (1920u*1080u*4u)
static HANDLE log_file=INVALID_HANDLE_VALUE;
static HCRYPTPROV crypto;
static unsigned char retention[27000], *pixels, pcm_hash[32];
static const unsigned char *pcm_pointer;
static char directory[2048];
static DWORD sequence, frame, phase, pcm_phase, thread_id, failed, ended;
static unsigned char current[284];
static int write_all(HANDLE f,const void *data,DWORD bytes) {
    DWORD done=0; return WriteFile(f,data,bytes,&done,NULL) && done==bytes;
}
static int digest(const void *data,DWORD bytes,unsigned char out[32]) {
    HCRYPTHASH hash; DWORD size=32;
    if(!CryptCreateHash(crypto,CALG_SHA_256,0,0,&hash)) return 0;
    int ok=CryptHashData(hash,data,bytes,0) && CryptGetHashParam(hash,HP_HASHVAL,out,&size,0) && size==32;
    CryptDestroyHash(hash); return ok;
}
static int event(DWORD kind,const void *data,DWORD bytes) {
    DWORD header[4]={++sequence,GetCurrentThreadId(),kind,bytes};
    return write_all(log_file,header,sizeof(header)) && write_all(log_file,data,bytes);
}
static int save(const char *name,const void *data,DWORD bytes) {
    char path[2304]; snprintf(path,sizeof(path),"%s/%s",directory,name);
    HANDLE file=CreateFileA(path,GENERIC_WRITE,0,NULL,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,NULL);
    if(file==INVALID_HANDLE_VALUE) return 0;
    int ok=write_all(file,data,bytes) && FlushFileBuffers(file);
    CloseHandle(file); return ok;
}
__declspec(dllexport) DWORD __cdecl capture_init(const char *output,const unsigned char *keep) {
    if(log_file!=INVALID_HANDLE_VALUE || strlen(output)>=sizeof(directory)) return 1;
    strcpy(directory,output); memcpy(retention,keep,sizeof(retention));
    char path[2304]; snprintf(path,sizeof(path),"%s/events.bin",directory);
    log_file=CreateFileA(path,GENERIC_WRITE,FILE_SHARE_READ,NULL,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,NULL);
    pixels=VirtualAlloc(NULL,PIXELS,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);
    if(log_file==INVALID_HANDLE_VALUE || !pixels || !CryptAcquireContextA(&crypto,NULL,NULL,PROV_RSA_AES,CRYPT_VERIFYCONTEXT)) return 2;
    return write_all(log_file,"EIDCAP01",8)?0:3;
}
static int read_pixels(void) {
    const GLenum keys[8]={0x0d00,0x0d01,0x0d02,0x0d03,0x0d04,0x0d05,0x806b,0x806c};
    GLint old[8], read, draw_fbo, read_fbo, pbo, viewport[4], bits[4], samples, srgb;
    GLenum initial_error=glGetError();
    if(initial_error!=GL_NO_ERROR) {printf("CAPTURE_GL_PREEXISTING_ERROR %x\n",initial_error);fflush(stdout);return 0;}
    glGetIntegerv(0x8ca6,&draw_fbo); glGetIntegerv(0x8caa,&read_fbo); glGetIntegerv(0x88ed,&pbo);
    glGetIntegerv(GL_VIEWPORT,viewport); glGetIntegerv(GL_READ_BUFFER,&read);
    for(unsigned i=0;i<4;i++) glGetIntegerv(GL_RED_BITS+i,&bits[i]);
    glGetIntegerv(0x80a9,&samples); glGetIntegerv(0x8db9,&srgb);
    if(draw_fbo || read_fbo || pbo || viewport[0] || viewport[1] || viewport[2]!=1920 || viewport[3]!=1080) {printf("CAPTURE_GL_BINDING fbo=%d/%d pbo=%d viewport=%d,%d,%d,%d\n",draw_fbo,read_fbo,pbo,viewport[0],viewport[1],viewport[2],viewport[3]);fflush(stdout);return 0;}
    if(bits[0]!=8 || bits[1]!=8 || bits[2]!=8 || bits[3]!=8 || samples || srgb) {printf("CAPTURE_GL_LAYOUT bits=%d,%d,%d,%d samples=%d srgb=%d\n",bits[0],bits[1],bits[2],bits[3],samples,srgb);fflush(stdout);return 0;}
    for(unsigned i=0;i<8;i++) glGetIntegerv(keys[i],&old[i]);
    for(unsigned i=0;i<8;i++) glPixelStorei(keys[i],i==5?1:0);
    glReadBuffer(GL_BACK); glReadPixels(0,0,1920,1080,GL_RGBA,GL_UNSIGNED_BYTE,pixels);
    GLenum error=glGetError();
    glReadBuffer(read); for(unsigned i=0;i<8;i++) glPixelStorei(keys[i],old[i]);
    if(error!=GL_NO_ERROR || glGetError()!=GL_NO_ERROR) return 0;
    for(unsigned i=0;i<8;i++) { GLint value; glGetIntegerv(keys[i],&value); if(value!=old[i]) return 0; }
    GLint restored; glGetIntegerv(GL_READ_BUFFER,&restored); if(restored!=read) return 0;
    GLint witness[18];memcpy(witness,old,32);witness[8]=read;
    for(unsigned i=0;i<8;i++)glGetIntegerv(keys[i],&witness[9+i]);
    witness[17]=restored;
    char witness_name[64];snprintf(witness_name,sizeof(witness_name),"gl-%05lu.bin",frame);
    if(!save(witness_name,witness,sizeof(witness)))return 0;
    DWORD layout[16]={frame,1920,1080,8,8,8,8,0,0,0,0,0,0x405,0,0,0};
    if(!event(10,layout,sizeof(layout))) return 0;
    unsigned char record[36]; memcpy(record,&frame,4);
    if(!digest(pixels,PIXELS,record+4) || !event(8,record,36)) return 0;
    if(retention[frame]) { char name[64]; snprintf(name,sizeof(name),"frame-%05lu.raw",frame); if(!save(name,pixels,PIXELS)) return 0; }
    return 1;
}
static DWORD capture(DWORD kind,const unsigned char *data,DWORD bytes) {
    if(failed || ended || log_file==INVALID_HANDLE_VALUE) return 10;
    if(!thread_id) thread_id=GetCurrentThreadId();
    if(thread_id!=GetCurrentThreadId()) return 11;
    if(kind==6 || kind==7) {
        unsigned char hash[32];
        if(bytes!=PCM_BYTES || kind!=6+pcm_phase || phase || !digest(data,bytes,hash)) return 12;
        if(kind==6) { memcpy(pcm_hash,hash,32); pcm_pointer=data; if(!save("pcm.f32le",data,bytes)) return 13; }
        else if(data!=pcm_pointer || memcmp(hash,pcm_hash,32)) return 14;
        pcm_phase++; return event(kind,hash,32)?0:15;
    }
    if(bytes!=284 || pcm_phase!=2 || kind<1 || kind>5) return 16;
    const DWORD *words=(const DWORD *)data;
    if(kind==1) {
        if(phase || frame || words[0] || words[1]) return 17;
        phase=1;
    } else if(kind==2) {
        if(phase!=1 || frame>=27000 || words[0]!=frame || words[1]!=735*frame) return 18;
        memcpy(current,data,284); phase=2;
    } else if(kind==3) {
        if(phase!=2 || memcmp(current,data,284)) return 19;
        phase=3;
    } else if(kind==4) {
        if(phase!=3 || memcmp(current,data,284)) return 20;
        phase=1;
    } else {
        if(phase!=1 || frame!=27000 || words[0]!=27000 || words[1]!=19845000 || words[4]!=0xffffffff) return 21;
    }
    if(!event(kind,data,bytes)) return 22;
    if(kind==3 && !read_pixels()) return 23;
    if(kind==4) frame++;
    if(kind==5) {
        unsigned char hash[32];
        if(!digest(pcm_pointer,PCM_BYTES,hash) || memcmp(hash,pcm_hash,32) || !event(9,hash,32)) return 24;
        ended=1;
        if(!FlushFileBuffers(log_file)) return 25;
    }
    return 0;
}
__declspec(dllexport) DWORD __cdecl capture_event(DWORD kind,const unsigned char *data,DWORD bytes) {
    /* Preserve full x87/SSE state around helper work; live hook/GL effects still need review. */
    unsigned char fp[512] __attribute__((aligned(16)));
    __asm__ __volatile__("fxsave %0":"=m"(fp));
    DWORD result=capture(kind,data,bytes); if(result) failed=result;
    __asm__ __volatile__("fxrstor %0"::"m"(fp));
    return result;
}
__declspec(dllexport) DWORD __cdecl capture_cursor(void) { return frame*735; }
BOOL WINAPI DllMain(HINSTANCE module,DWORD reason,LPVOID reserved) {
    (void)module;(void)reason;(void)reserved;return TRUE;
}
