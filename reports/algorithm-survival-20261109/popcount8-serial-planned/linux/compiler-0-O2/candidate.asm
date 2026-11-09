
/work/experiments/runs/algorithm-survival-20261109/popcount8-serial-planned/linux/compiler-0-O2/candidate.o:	file format elf64-littleaarch64

Disassembly of section .text:

0000000000000000 <popcount8>:
       0:      	adrp	x8, 0x0 <popcount8>
       4:      	dup	v0.4s, w0
       8:      	movi	v2.4s, #0x1
       c:      	ldr	q1, [x8]
      10:      	sbfx	w8, w0, #0, #1
      14:      	mov	w9, #0x75c1             // =30145
      18:      	mov	w10, #0xa03b            // =41019
      1c:      	mov	w11, #0x2a7a            // =10874
      20:      	movk	w9, #0xd0f0, lsl #16
      24:      	ushl	v0.4s, v0.4s, v1.4s
      28:      	tst	w0, #0x2
      2c:      	movk	w10, #0xf771, lsl #16
      30:      	movk	w11, #0x2681, lsl #16
      34:      	and	w8, w8, w9
      38:      	csel	w9, w11, w10, eq
      3c:      	ubfx	w10, w0, #2, #1
      40:      	mov	w11, #0xd306            // =54022
      44:      	and	v0.16b, v0.16b, v2.16b
      48:      	add	w8, w8, w9
      4c:      	mov	w9, #0x9a41             // =39489
      50:      	movk	w9, #0x2b1c, lsl #16
      54:      	movk	w11, #0x624e, lsl #16
      58:      	madd	w8, w8, w9, w10
      5c:      	ubfx	w9, w0, #7, #1
      60:      	addv	s0, v0.4s
      64:      	add	w8, w8, w11
      68:      	fmov	w10, s0
      6c:      	add	w9, w10, w9
      70:      	add	w0, w8, w9
      74:      	ret
