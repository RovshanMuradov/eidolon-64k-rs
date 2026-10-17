# 1. Packing and startup

The EXE is a 58 844-byte kkrunchy stream plus 2 084 bytes of wrapper. The unpacker restores the code, resolves 35 imports and jumps to `0x406379`.

## File layout

The outer wrapper takes 2 084 bytes; the decoder itself is 1 596 of them.

| File offset | Bytes | Contents |
|---|---:|---|
| `[0, 0xd4)` | 212 | Compact DOS, PE and section headers |
| `[0xd4, 0xe6b0)` | 58 844 | Joint compressed stream (range coder) |
| `[0xe6b0, 0xe786)` | 214 | Decoder helper functions |
| `[0xe786, 0xec94)` | 1 294 | Decoder entry, model, decode loop |
| `[0xec94, 0xecec)` | 88 | Squash and context-mask constants |
| `[0xecec, 0xed58)` | 108 | Loader imports: `KERNEL32!LoadLibraryA`, `GetProcAddress` |
| `[0xed58, 0xee00)` | 168 | Zero padding |

`SizeOfHeaders = 4096` is the mapped size, not bytes actually used: compressed data starts at `0xd4`.

## kkrunchy (k7) decoder

The decoder is an arithmetic coder with context mixing:
- 11 context models, match and run prediction;
- MMX model mixing, adaptive probability mapping;
- skipping of 8 192-byte zero blocks;
- state tables are generated at startup, not stored in the file.

## Inner loader

The loader is 1 501 bytes and sits inside the compressed stream.

| Address | Bytes | Role |
|---|---:|---|
| `0x3f942d` | 64 | Inverse filter setup, end check |
| `0x3f946d` | 55 | Stack restore, import loading by name and ordinal |
| `0x3f94a4` | 5 | Jump to `0x406379` |
| `0x3f94a9` | 465 | Inverse x86 code transform |
| `0x3f967a` | 256 | Opcode class table |
| `0x3f977a` | 576 | Application import records |
| `0x3f99ba` | 80 | Lengths of the 20 filter streams |

**x86 filter.** Before compression the code is split into 20 streams (opcodes, ModRM, displacements, branch targets, etc.) so the compressor sees uniform contexts. The inverse filter rebuilds 30 279 bytes of code at `[0x401000, 0x408647)`.

## Control transfer

```
0x3ee944 decoder → 0x3f942d loader → 0x3f94a4 → 0x406379 application
```

The loader writes `0x3e0000` to `0x400000` (compatibility patch), resolves imports via `LoadLibraryA` / `GetProcAddress`, and returns on failure.

## Application imports

35 functions from 5 DLLs:

| DLL | IAT | Functions |
|---|---|---|
| KERNEL32 | `0x409010` | GlobalAlloc, GlobalFree, CreateThread, CloseHandle, lstrcmpiA, GetTickCount, GetSystemDirectoryA, CreateFileA, ExitProcess, ReadFile |
| USER32 | `0x409068` | PeekMessageA, CreateWindowExA, GetClientRect, TranslateMessage, DispatchMessageA, GetDC, GetAsyncKeyState, ShowCursor |
| GDI32 | `0x409000` | SetPixelFormat, ChoosePixelFormat, SwapBuffers |
| OPENGL32 | `0x40903c` | glGenTextures, wglMakeCurrent, glGetTexImage, glTexImage2D, glTexParameteri, wglGetProcAddress, wglCreateContext, glBindTexture, glRecti, glViewport |
| WINMM | `0x40908c` | waveOutPrepareHeader, waveOutOpen, waveOutWrite, waveOutGetPosition |

OpenGL functions newer than 1.1 (`glCreateShaderProgramv`, FBOs, uniforms, 3D textures) are loaded through `wglGetProcAddress`.

## The `gm.dls` sample bank

The intro reads the system General MIDI bank. The path is built during synth initialization:

```
GetSystemDirectoryA(buf, 0x400)                // usually C:\Windows\system32
strcat(buf, "\drivers\gm.dls")                 // string at 0x409330
h = CreateFileA(buf, GENERIC_READ, 0, 0, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, 0)   // 0x40121f
ReadFile(h, 0x4c0c70, 0x9fffff, &n, 0)         // 0x40123e, up to ~10 MB in one call
CloseHandle(h)                                 // 0x401245
```

- Errors are not checked. Without the file the synth crashes on a null sample pointer (`0x404d7b`).
- The bank is scanned for the 4-byte tag `data`: each chunk found is one sample, its length taken from the next word (`0x40125f`).
- The reference bank is 3 440 660 bytes. 15 samples are actually heard (see [06-audio.md](06-audio.md)).
