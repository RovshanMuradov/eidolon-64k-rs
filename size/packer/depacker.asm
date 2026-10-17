; kkrunchy_k7 depacker (asm version), extended context model
; fabian "ryg/farbrausch" giesen 2006; model extensions and size rework 2026
; I hereby place this code in the public domain.

bits          32

%define NMODEL    14
%define NINPUT    60
%define NMIX      7
%define NWEIGHT   (6400)
%define WK        0x2f0b4ae5
%define LR        7
%define SM        9
%define APMR      7
%define ST        1
%define DP        8
%define MX        3
%define RT        3
%define AC        8

%define MEMSHIFT  23
%define MEM       (1<<MEMSHIFT)
%define MAXLEN    2047
%define APMSIZE   8192

struc ContextModel
  .cpr        resd 1
  .cps        resd 1
  .ctx        resd 1
  .st         resd 1
  .size:
endstruc

; ---- work area; ebp points at W_src (offset 0), tx sits just below it

%define WBIAS (NINPUT*2+8)
absolute      -WBIAS
W_zeroprob    resd 1
W_bitcounter  resd 1
W_tx          resw NINPUT
W_src         resd 1
W_dst         resd 1
W_csub        resd 1
W_range       resd 1
W_outsize     resd 1
W_c0          resd 1
W_c0s         resd 1
W_bpos        resd 1
W_matchp      resd 1
W_matchl      resd 1
W_matchw      resd 1
W_bit         resd 1
W_bitscaled   resd 1
W_origdst     resd 1
W_wh2         resd 1
W_ctx         resd NMIX
W_pr          resd NMIX+1
W_outprob     resd 1
W_tx2         resw 8
W_APMi        resd 1   ; disp32: keeps tx2 within disp8 range
W_wx2         resw 8
W_cm          resb ContextModel.size * NMODEL
W_match       resd MEM/16  ; must follow W_cm
W_modelMem    resb MEM
W_wx          resw NINPUT*NWEIGHT
W_sq          resw 33
W_runTable    resd 256
W_stateCode   resb 256*2  ; must follow immediately after runTable
W_stateNext   resb 256*2
W_stateMap    resd 256
W_stretch     resd 4096
W_APM         resd APMSIZE*33
W_end:

section       .bss

WorkData      resb W_end + WBIAS
%define WD    (WorkData+WBIAS)

; ---- fixups

extern        PACKED
extern        DEPACKED
extern        DEPACKEDSIZE
extern        IMPORTS
extern        LOADLIBRARY

extern        PATCHOFFS
extern        PATCHVALUE

global        STAGE0ENTRY

; ---- code

section       .text

; squash
;   in: eax
;   out: eax
;   destroy: ecx,edx

squash:
  cmp       eax, -2047
  jl        .small
  cmp       eax, 2047
  jle       .notbig
  mov       eax, 2047     ; squash(2047) = 4095

.notbig:
  mov       ecx, eax
  sar       ecx, 7
  lea       ecx, [WD+W_sq+ecx*2+16*2]
  and       eax, byte 127
  mov       edx, [ecx+2]
  sub       edx, [ecx]
  movzx     edx, dx
  imul      eax, edx
  add       eax, byte 64
  sar       eax, 7
  add       ax, [ecx]
  ret

.small:
  xor       eax, eax
  ret

; contextHash
;   in: eax=i
;   out: eax=p
;   destroy: edx

contextHash:
  mov       edx, eax
  shr       edx, 24
  and       eax, ((MEM / 4) - 1) & ~1
  lea       eax, [ebp+W_modelMem+eax*4]

  cmp       dl, [eax]
  je        .found
  add       eax, byte 4
  cmp       dl, [eax]
  je        .found

  mov       dh, [eax+1]
  cmp       dh, [eax-3]
  jbe       .noswap
  sub       eax, byte 4

.noswap:
  movzx     edx, dl
  mov       [eax], edx

.found:
  inc       eax
  ret

; train
;   in: eax=err
;       esi=t
;       edi=w
;       ecx=n/4
;   out: esi,edi advanced.
train:
  movd      mm0, eax
  punpcklwd mm0, mm0
  punpcklwd mm0, mm0
  pcmpeqb   mm1, mm1
  psrlw     mm1, 15

.lp:
  movq      mm3, [esi]
  movq      mm2, [edi]
  paddsw    mm3, mm3
  pmulhw    mm3, mm0
  paddsw    mm3, mm1
  psraw     mm3, 1
  paddsw    mm2, mm3
  movq      [edi], mm2
  add       esi, byte 8
  add       edi, byte 8
  loop      .lp

  ret

; decodebit
;   in: eax=prob
;   out: edx=bit; eax, ecx destroyed

decodebit:
  mov       ecx, [ebp+W_src]
  mul       dword [ebp+W_range]
  shrd      eax, edx, 12

  mov       ecx, [ecx]
  bswap     ecx
  sub       ecx, [ebp+W_csub]
  xor       edx, edx
  cmp       eax, ecx
  ja        .one

  add       [ebp+W_csub], eax
  sub       [ebp+W_range], eax
  jmp       short .renorm

.one:
  mov       [ebp+W_range], eax
  inc       edx

.renorm:
  cmp       byte [ebp+W_range+3], 0
  jne       .done

  ; renormalize
  inc       dword [ebp+W_src]
  shl       dword [ebp+W_range], 8
  shl       dword [ebp+W_csub], 8
  jmp       short .renorm

.done:
  ret

; ---- the actual depacker entry

STAGE0ENTRY:
  mov       ebp, WD
  mov       dword [ebp+W_src], PACKED
  mov       eax, DEPACKED
  mov       [ebp+W_dst], eax
  mov       [ebp+W_origdst], eax
  push      eax
  mov       dword [ebp+W_outsize], DEPACKEDSIZE

; ---- model initialization (assumes everything filled with zero)

  dec       dword [ebp+W_range]
  inc       dword [ebp+W_c0]
  inc       dword [ebp+W_zeroprob]
  mov       byte [ebp+W_bpos], 8
  mov       eax, 2048
  lea       edi, [ebp+W_pr]
  push      byte NMIX+2
  pop       ecx
  rep       stosd

  ; squash table and first APM row: round(4096/(1+e^((16-j)/2))), j=0..32
  ; (assumes ecx=0)
  mov       edi, WD+W_sq
  mov       esi, WD+W_APM
  mov       cl, 33
  fld       dword [sqR0]
.sqLoop:
  fld1
  fadd      st0, st1
  fidivr    dword [sq4096]
  fistp     word [edi]
  movzx     eax, word [edi]
  shl       eax, 4
  mov       [esi], eax
  scasw
  lodsd
  fmul      dword [sqQ]
  loop      .sqLoop
  fstp      st0

  ; initialize run table via numerical integration of 1/x
  mov       ebx, 14155776
  mov       edi, WD+W_runTable+4
  inc       ecx

.runTableLoop:
  lea       esi, [ecx*2+1]
  mov       eax, 774541002
  cdq
  div       esi
  add       ebx, eax
  mov       eax, ebx
  shr       eax, 21
  stosd
  inc       cl
  jnz       .runTableLoop

  ; build state table.
  ; note: edi already points to stateCode
  ; assumes ecx=0
  mov       esi, WD+W_stateNext
  xor       ebx, ebx
  mov       cl, 4

.stateTableLoop:
  xor       ebx, byte 1
  mov       ah, [edi+ebx]
  cmp       ah, 2
  jbe       .log_underflow

  movzx     eax, ah
  mov       eax, [WD+W_runTable+eax*4-4]
  shl       eax, 2
  dec       ah

.log_underflow:
  xor       ebx, byte 1
  mov       al, [edi+ebx]

  inc       eax
  cmp       al, 40
  jbe       .no_inc_overflow
  mov       al, 40

.no_inc_overflow:
  test      bl, 1
  jz        .bit_even
  xchg      al, ah

.bit_even:
  push      edi
  mov       edx, ecx
  repne     scasw
  je        .found
  inc       edx
  scasw

.found:
  not       ecx
  add       ecx, edx
  mov       [edi-2], ax
  mov       [esi], cl
  inc       esi
  mov       ecx, edx
  pop       edi
  inc       ebx

  cmp       bh, 2
  jne       .stateTableLoop

  ; build initial state map.
  ; note that ecx=0x100 at this point
  mov       esi, edi
  mov       edi, WD+W_stateMap

.stateMapLoop:
  xor       eax, eax
  lodsb
  mov       ebx, eax
  lodsb
  inc       eax
  inc       ebx
  add       ebx, eax
  shl       eax, 16
  cdq
  div       ebx
  stosd
  loop      .stateMapLoop

  ; transform state code table to and masks
  mov       ch, 2
  mov       esi, WD+W_stateCode
  mov       edi, esi

.stateCodeLoop:
  lodsb
  sub       al, 1
  salc
  stosb
  loop      .stateCodeLoop

  ; build stretch table (inverse of squash)
  mov       edi, WD+W_stretch
  or        ebx, byte -1 ; =previous i
  mov       eax, -2047

.stretchLoop:
  push      eax
  call      squash

  mov       ecx, eax
  sub       ecx, ebx
  mov       ebx, eax
  pop       eax
  rep       stosd

  inc       eax
  cmp       eax, 2048
  jle       .stretchLoop

  ; initialize context models: on the zeroed hash table contextHash(1) and
  ; contextHash(0) both return modelMem+1
  ; assumes ecx=0 here
  mov       edi, WD+W_cm
  mov       eax, WD+W_modelMem+1
  mov       cl, NMODEL

.ctxModelLoop:
  stosd
  stosd
  scasd
  scasd
  loop      .ctxModelLoop

  ; clone the first APM row; APM[0] = squash(-2048)<<4 = 0 (assumes ecx=0)
  mov       esi, WD+W_APM
  mov       [esi], ecx
  lea       edi, [esi+33*4]
  mov       ecx, (APMSIZE-1)*33
  rep       movsd

; ---- main decoding loop

  xor       ebx, ebx ; =byte
  inc       ebx

.decodebitloop:
  xor       eax, eax
  cmp       eax, [ebp+W_bitcounter]
  jne       .nozeropage

  mov       eax, [ebp+W_zeroprob]
  call      decodebit

  mov       eax, [ebp+W_zeroprob]
  neg       edx
  inc       eax
  shr       edx, 32-12 ; eqv. to and edx, 4095 here
  add       eax, edx
  shr       eax, 1
  mov       [ebp+W_zeroprob], eax

  test      edx, edx
  jz        .nozeropage

  mov       eax, 8192
  add       [ebp+W_dst], eax
  sub       [ebp+W_outsize], eax
  jmp       short .decodebitloop

.nozeropage:
  mov       eax, [ebp+W_outprob]
  cmp       ah, 8
  adc       eax, byte 0

  call      decodebit

  ; byte writing+prepare for model
  mov       [ebp+W_bit], edx
  inc       word [ebp+W_bitcounter]
  shr       edx, 1
  adc       bl, bl
  jnc       .decodenobytedone

  mov       eax, [ebp+W_dst]
  mov       [eax], bl
  inc       dword [ebp+W_dst]
  mov       bl, 1

  dec       dword [ebp+W_outsize]
  jnz       .decodenobytedone

  ; ---- import processing
.decodedone:
  emms
  pop       eax
  push      dword PATCHOFFS
  push      dword PATCHVALUE
  push      eax
  mov       esi, IMPORTS
  mov       ebx, LOADLIBRARY
  ret

.decodenobytedone:
  ; ---- model main loop
  push      ebx

  mov       ecx, [ebp+W_bit]
  shl       ecx, 16
  sub       ecx, byte -128
  mov       [ebp+W_bitscaled], ecx

  ; update mixers
  xor       edx, edx

.updmixer:
  mov       eax, [ebp+W_bit]
  shl       eax, 12
  sub       eax, [ebp+W_pr+edx*4]
  imul      eax, byte LR

  cmp       dl, NMIX
  je        .updmixerdone

  imul      edi, [ebp+W_ctx+edx*4], byte (NINPUT*2)
  lea       edi, [ebp+W_wx+edi]
  lea       esi, [ebp+W_tx]
  push      byte (NINPUT/4)
  pop       ecx
  call      train

  inc       edx
  jmp       short .updmixer

.updmixerdone:
  ; assumes ecx=0
  mov       edi, WD+W_wx2
  lea       esi, [ebp+W_tx2]
%if NMIX > 4
  mov       cl, 2
%else
  inc       ecx
%endif
  call      train

  ; update c0 and position in bit
  mov       eax, [ebp+W_bit]
  shl       dword [ebp+W_c0], 1
  add       [ebp+W_c0], eax

  dec       dword [ebp+W_bpos]
  jnz       near .nonewbyte

  ; assumes ecx=0
  mov       byte [ebp+W_bpos], 8
  inc       ecx
  mov       [ebp+W_c0], ecx

  ; word hash
  mov       edi, [ebp+W_dst]
  movzx     eax, byte [edi-1]
  mov       edx, [ebp+W_wh2]
  xor       edx, eax
  imul      edx, edx, WK
  or        al, 0x20
  sub       al, 'a'
  cmp       al, 26
  jb        .iswordch
  xor       edx, edx
.iswordch:
  mov       [ebp+W_wh2], edx

  ; update context models
  mov       esi, WD+W_cm
  xor       eax, eax
  push      byte NMODEL
  pop       ecx

.updcontext:
  and       eax, byte -2
  mov       [esi+ContextModel.ctx], eax

  ; update run context
  mov       ebx, [esi+ContextModel.cpr]
  mov       edi, [ebp+W_dst]
  mov       dh, [edi-1] ; bufPtr[-1]
  cmp       dh, [ebx+1] ; cpr[1]
  je        .norunflush
  mov       dl, 0
  mov       [ebx], dx

.norunflush:
  inc       byte [ebx]
  inc       eax
  call      contextHash
  mov       [esi+ContextModel.cpr], eax

  ; fnv hash function
  ; assumes edi=_bufPtr
  lea       eax, [ecx+1]
  imul      eax, eax, 0x811c9dc5
  mov       bl, [masks+ecx-1]
  mov       dh, [bitm+ecx-1]

.hashnext:
  dec       edi
  shr       bl, 1
  jnc       .hashnotset

  mov       dl, [edi]
  and       dl, dh
  xor       al, dl
  imul      eax, 0x01000193
  jmp       short .hashnext

.hashnotset:
  jnz       .hashnext

  ; position and word terms
  movzx     ebx, byte [posm+ecx-1]
  btr       ebx, 7
  sbb       edi, edi
  and       edi, [ebp+W_wh2]
  mov       edx, [ebp+W_dst]
  sub       edx, [ebp+W_origdst]
  and       edx, ebx
  xor       edx, edi
  xor       eax, edx
  imul      eax, eax, 0x01000193

  add       esi, byte ContextModel.size
  loop      .updcontext

  ; match processing
  ; assumes esi points to "match"
  and       eax, (MEM/16)-1
  mov       edi, [ebp+W_dst]
  xchg      edi, [esi+eax*4] ; now edi=Match[h]
  mov       esi, [ebp+W_dst]

  mov       ecx, [ebp+W_matchl]
  jecxz     .searchmatch

  inc       ecx
  inc       dword [ebp+W_matchp]
  jmp       short .updmatch

.searchmatch:
  test      edi, edi
  jz        .updmatch

  mov       [ebp+W_matchp], edi

  std
  cmpsb

  mov       ecx, edi
  sub       ecx, [ebp+W_origdst]
  push      ecx
  repe      cmpsb
  cld

  je        .allequal
  inc       ecx

.allequal:
  neg       ecx
  pop       eax
  add       ecx, eax

.updmatch:
  mov       eax, MAXLEN
  cmp       ecx, eax
  cmova     ecx, eax
  mov       [ebp+W_matchl], ecx

  cmp       ecx, byte 32
  jbe       .nolongmatch
  push      byte 32
  pop       ecx

.nolongmatch:
  shl       ecx, 6
  mov       [ebp+W_matchw], ecx

.nonewbyte:
  ; start model mixing
  mov       ecx, [ebp+W_c0]
  shl       ecx, 3
  mov       [ebp+W_c0s], ecx

  ; constant model
  lea       edi, [ebp+W_tx]
  push      byte 127
  pop       eax
  stosw

  ; match model
  xor       eax, eax
  cmp       eax, [ebp+W_matchl]
  je        .nomatch

  mov       ebx, [ebp+W_matchp]
  movzx     ebx, byte [ebx]
  inc       bh
  mov       cl, [ebp+W_bpos]
  shr       ebx, cl
  sbb       edx, edx
  cmp       ebx, [ebp+W_c0]
  jne       .nomatch

  mov       eax, [ebp+W_matchw]
  xor       eax, edx
  sub       eax, edx
  jmp       short .matchdone

.nomatch:
  mov       [ebp+W_matchl], eax

.matchdone:
  stosw

  mov       eax, [ebp+W_matchl]
  cmp       eax, 400
  jbe       .contextmodels

  mov       dword [ebp+W_ctx], 512+14
  jmp       .mix

  ; context models
.contextmodels:
  mov       esi, WD+W_cm
  xor       eax, eax
  mov       ah, 2
  mov       [ebp+W_ctx+8], eax
  push      byte NMODEL
  pop       ecx

.contextloop:
  ; run model
  push      ecx

  mov       eax, [esi+ContextModel.cpr]
  movzx     edx, byte [eax+1]
  movzx     eax, byte [eax]
  mov       cl, [ebp+W_bpos]
  inc       dh
  mov       eax, [WD+W_runTable+eax*4]
  shr       edx, cl
  sbb       ecx, ecx
  xor       eax, ecx
  sub       eax, ecx

  cmp       edx, [ebp+W_c0]
  je        .run
  xor       eax, eax

.run:
  stosw
  pop       ecx

  ; nonstationary context
  mov       eax, [esi+ContextModel.cps]
  mov       edx, [ebp+W_bit]
  movzx     ebx, byte [eax]
  mov       bl, [WD+W_stateNext+ebx*2+edx]
  mov       [eax], bl

  mov       eax, [esi+ContextModel.ctx]
  xor       eax, [ebp+W_c0s]
  call      contextHash
  mov       [esi+ContextModel.cps], eax
  movzx     ebx, byte [eax]

  ; state mapping
  mov       edx, [esi+ContextModel.st]
  lea       edx, [WD+W_stateMap+edx*4]
  mov       eax, [ebp+W_bitscaled]
  sub       eax, [edx]
  sar       eax, SM
  add       [edx], eax
  mov       [esi+ContextModel.st], ebx
  mov       eax, [WD+W_stateMap+ebx*4]
  shr       eax, 4
  push      eax
  mov       eax, [WD+W_stretch+eax*4]
  sar       eax, ST
  stosw
  pop       eax

  shr       eax, 4
  mov       edx, eax
  not       dl

  sub       eax, edx
  stosw
  add       eax, edx

  and       al, [WD+W_stateCode+ebx*2+0]
  and       dl, [WD+W_stateCode+ebx*2+1]
  sub       eax, edx
  stosw

  cmp       ebx, byte 1
  sbb       dword [ebp+W_ctx+8], byte -1

  add       esi, byte ContextModel.size
  dec       ecx
  jnz       near .contextloop

  ; weighting contexts
  mov       ebx, [ebp+W_dst]
  lea       edi, [ebp+W_ctx]
  movzx     eax, byte [ebx-1]
  stosd
  mov       ecx, [ebp+W_c0]
  mov       al, cl
  inc       ah
  stosd
  scasd
  mov       eax, ebx
  sub       eax, [ebp+W_origdst]
  and       eax, 3
  add       al, 3
  mov       ah, al
  mov       al, cl
  stosd
  movzx     eax, byte [ebx-1]
  shr       eax, 4
  add       al, 7
  mov       ah, al
  mov       al, cl
  stosd
  movzx     eax, byte [ebx-2]
  mov       ah, 23
  stosd
  movzx     eax, byte [ebx-3]
  mov       ah, 24
  stosd

  xor       ebx, ebx
  mov       eax, [ebp+W_matchl]
  dec       eax
  cmovs     eax, ebx
  not       bl
  cmp       eax, ebx
  cmova     eax, ebx
  mov       eax, [ebp+W_runTable+eax*4]
  shr       eax, RT
  add       [ebp+W_ctx+8], eax

.mix:
  ; perform mixing
  push      byte NMIX-1
  pop       ebx

.mixloop:
  imul      edi, [ebp+W_ctx+ebx*4], byte (NINPUT*2)
  lea       edi, [ebp+W_wx+edi]
  lea       esi, [ebp+W_tx]

  pxor      mm0, mm0
  push      byte (NINPUT/4)
  pop       ecx

.mixdploop:
  movq      mm1, [esi]
  pmaddwd   mm1, [edi]
  psrad     mm1, DP
  paddd     mm0, mm1
  add       esi, byte 8
  add       edi, byte 8
  loop      .mixdploop

  movq      mm1, mm0
  psrlq     mm1, 32
  paddd     mm0, mm1
  movd      eax, mm0
  sar       eax, MX

  mov       [ebp+W_tx2+ebx*2], ax
  call      squash
  mov       [ebp+W_pr+ebx*4], eax

  dec       ebx
  jns       .mixloop

  ; the final mix
  lea       esi, [ebp+W_tx2]
  mov       edi, WD+W_wx2
  xor       eax, eax
  push      byte NMIX
  pop       ecx

.finalmix:
  movsx     ebx, word [edi]
  movsx     edx, word [esi]
  imul      ebx, edx
  add       eax, ebx
  cmpsw
  loop      .finalmix

  sar       eax, 16
  call      squash
  mov       [ebp+W_pr+NMIX*4], eax

  ; APM stage
  ; assumes p still in eax
  mov       ecx, [ebp+W_bit]
  mov       edx, [ebp+W_APMi]
  lea       edi, [ebp+W_APM+16*4+edx*4]
  neg       ecx
  and       ecx, 0x100fe ;=g

  ; update APM tables
  push      ecx
  sub       ecx, [edi]
  sar       ecx, APMR
  add       [edi], ecx
  scasd
  pop       ecx
  sub       ecx, [edi]
  sar       ecx, APMR
  add       [edi], ecx

  ; calc new APM index
  mov       ebx, [ebp+W_dst]
  movzx     ebx, byte [ebx-1]
  imul      ebx, ebx, (1<<AC)+1
  add       ebx, [ebp+W_c0]
  and       ebx, APMSIZE-1
  imul      ebx, ebx, byte 33

  ; calc pf/finish APMi
  mov       ecx, [ebp+W_stretch+eax*4]
  push      ecx
  sar       ecx, 7
  add       ebx, ecx
  mov       [ebp+W_APMi], ebx
  pop       ecx

  ; calc p
  and       ecx, byte 127
  lea       esi, [ebp+W_APM+16*4+ebx*4]
  lodsd
  mov       ebx, [esi]
  sub       ebx, eax
  shl       eax, 7
  imul      ebx, ecx
  add       eax, ebx
  shr       eax, 11
  cmp       ah, 16
  jb        .apmok
  mov       ax, 4095
.apmok:
  mov       [ebp+W_outprob], eax

  pop       ebx
  jmp       .decodebitloop

; ---- initialized data

section       .data

sqR0          dd    2980.9579870417283   ; e^8
sqQ           dd    0.6065306597126334   ; e^-0.5
sq4096        dd    4096
masks         db 0x33, 0xe1, 0x0e, 0x03, 0x0d, 0x19, 0x07, 0x03, 0xa2, 0x02, 0x01, 0x00, 0x00, 0x01
bitm          db 0xfd, 0x7f, 0xff, 0xe0, 0xf8, 0xff, 0x7f, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff
posm          db 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x03, 0x80, 0x81
