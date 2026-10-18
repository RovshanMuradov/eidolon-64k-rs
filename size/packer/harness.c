/* Freestanding i386 Linux depacker harness. No libc or Windows image execution.
   The assembly test hook jumps here immediately after the prefilter decode. */
typedef unsigned char u8;
typedef unsigned int u32;

u8 PACKED[1 << 20] __attribute__((aligned(16)));
struct { u8 guard[64]; u8 data[1 << 20]; } OUTBUF __attribute__((aligned(16)));
extern u8 DEPACKEDSIZE[];
extern void STAGE0ENTRY(void);

static int sys3(int nr, int a, void *b, int c)
{
  int result;
  __asm__ volatile("int $0x80" : "=a"(result) : "a"(nr), "b"(a), "c"(b), "d"(c) : "memory");
  return result;
}

__attribute__((noreturn)) static void sysexit(int status)
{
  __asm__ volatile("int $0x80" :: "a"(1), "b"(status) : "memory");
  __builtin_unreachable();
}

void harness_done(void)
{
  __asm__ volatile("emms");
  u32 size = (u32)DEPACKEDSIZE, sent = 0;
  for(u32 i = 0; i < 64; i++)
    if(OUTBUF.guard[i] != 0 || OUTBUF.data[size + i] != 0xa5) sysexit(7);
  while(sent < size)
  {
    int n = sys3(4, 1, OUTBUF.data + sent, size - sent);
    if(n <= 0) sysexit(6);
    sent += n;
  }
  sysexit(0);
}

void _start(void)
{
  u32 size = 0;
  for(u32 i = 0; i < 64; i++) OUTBUF.data[(u32)DEPACKEDSIZE + i] = 0xa5;
  for(;;)
  {
    int n = sys3(3, 0, PACKED + size, sizeof(PACKED) - 64 - size);
    if(n < 0) sysexit(2);
    if(!n) break;
    size += n;
  }
  STAGE0ENTRY();
  sysexit(9);
}
