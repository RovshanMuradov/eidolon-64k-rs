.text
.globl _marker_hook
_marker_hook:
 pushfl
 pushal
 movl %esp,%ebp
 andl $-16,%esp
 subl $1056,%esp
 movl %esp,%edi
 xorl %eax,%eax
 movl $256,%ecx
 cld
 rep stosl
 fxsave (%esp)
 movl %esp,%eax
 subl $8,%esp
 pushl %eax
 pushl %ebp
 call _marker_observe
 addl $16,%esp
 fxrstor (%esp)
 fxsave 512(%esp)
 leal 512(%esp),%eax
 subl $8,%esp
 pushl %eax
 leal 12(%esp),%eax
 pushl %eax
 call _marker_check_fp
 addl $16,%esp
 fxrstor (%esp)
 movl %ebp,%esp
 popal
 popfl
 pushfl
 pushal
 movl %esp,%ebp
 andl $-16,%esp
 subl $512,%esp
 fxsave (%esp)
 subl $12,%esp
 pushl %ebp
 call _marker_check_gpr
 addl $16,%esp
 fxrstor (%esp)
 movl %ebp,%esp
 popal
 popfl
 jmp *_marker_trampoline

.globl _position_gate
_position_gate:
 pushfl
 pushal
 movl %esp,%ebp
 andl $-16,%esp
 subl $512,%esp
 fxsave (%esp)
 subl $12,%esp
 pushl %ebp
 call _position_begin
 addl $16,%esp
 fxrstor (%esp)
 subl $4,%esp
 pushl 48(%ebp)
 pushl 44(%ebp)
 pushl 40(%ebp)
 call _position_body@12
 addl $4,%esp
 movl %eax,28(%ebp)
 fxrstor (%esp)
 movl %ebp,%esp
 popal
 popfl
 pushfl
 pushal
 movl %esp,%ebp
 andl $-16,%esp
 subl $512,%esp
 fxsave (%esp)
 subl $12,%esp
 pushl %ebp
 call _position_check_gpr
 addl $16,%esp
 fxrstor (%esp)
 movl %ebp,%esp
 popal
 popfl
 ret $12

.macro OBSERVE_GATE name, target
.globl _\name\()_gate
_\name\()_gate:
 pushfl
 pushal
 movl %esp,%ebp
 andl $-16,%esp
 subl $1056,%esp
 movl %esp,%edi
 xorl %eax,%eax
 movl $256,%ecx
 cld
 rep stosl
 fxsave (%esp)
 movl %esp,%eax
 subl $8,%esp
 pushl %eax
 pushl %ebp
 call _\name\()_observe
 addl $16,%esp
 fxrstor (%esp)
 fxsave 512(%esp)
 leal 512(%esp),%eax
 subl $8,%esp
 pushl %eax
 leal 12(%esp),%eax
 pushl %eax
 call _\name\()_check_fp
 addl $16,%esp
 fxrstor (%esp)
 movl %ebp,%esp
 popal
 popfl
 pushfl
 pushal
 movl %esp,%ebp
 andl $-16,%esp
 subl $512,%esp
 fxsave (%esp)
 subl $12,%esp
 pushl %ebp
 call _\name\()_check_gpr
 addl $16,%esp
 fxrstor (%esp)
 movl %ebp,%esp
 popal
 popfl
 jmp *_\target
.endm
OBSERVE_GATE seed,seed_trampoline
OBSERVE_GATE draw,real_rect
