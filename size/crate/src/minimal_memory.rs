//! x86 cdecl memory/probe primitives, independent of CRT initialization.
core::arch::global_asm!(r#"
.section .text
.global _memcpy
_memcpy:
    push edi
    push esi
    mov edi, [esp+12]
    mov esi, [esp+16]
    mov ecx, [esp+20]
    mov eax, edi
    cld
    rep movsb
    pop esi
    pop edi
    ret
.global _strlen
_strlen:
    push edi
    mov edi, [esp+8]
    xor eax, eax
    or ecx, -1
    cld
    repne scasb
    not ecx
    lea eax, [ecx-1]
    pop edi
    ret
.global _memmove
_memmove:
    push edi
    push esi
    mov edi, [esp+12]
    mov esi, [esp+16]
    mov ecx, [esp+20]
    mov eax, edi
    test ecx, ecx
    jz 2f
    cmp edi, esi
    jbe 1f
    lea edi, [edi+ecx-1]
    lea esi, [esi+ecx-1]
    std
    rep movsb
    jmp 2f
1:
    cld
    rep movsb
2:
    cld
    pop esi
    pop edi
    ret
.global _memset
_memset:
    push edi
    mov edi, [esp+8]
    mov eax, [esp+12]
    mov ecx, [esp+16]
    cld
    rep stosb
    mov eax, [esp+8]
    pop edi
    ret
.global _memcmp
_memcmp:
    push edi
    push esi
    mov esi, [esp+12]
    mov edi, [esp+16]
    mov ecx, [esp+20]
    xor eax, eax
    test ecx, ecx
    jz 4f
3:
    movzx eax, byte ptr [esi]
    movzx edx, byte ptr [edi]
    sub eax, edx
    jnz 4f
    inc esi
    inc edi
    dec ecx
    jnz 3b
4:
    pop esi
    pop edi
    ret
.global ___chkstk_ms
___chkstk_ms:
    push ecx
    push eax
    lea ecx, [esp+12]
5:
    cmp eax, 4096
    jb 6f
    sub ecx, 4096
    test [ecx], eax
    sub eax, 4096
    jmp 5b
6:
    sub ecx, eax
    test [ecx], eax
    pop eax
    pop ecx
    ret
"#);
