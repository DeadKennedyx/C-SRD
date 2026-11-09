
/work/experiments/runs/algorithm-survival-20261109/popcount8-swar-identity/linux/compiler-0-O2/original.o:	file format elf64-littleaarch64

Disassembly of section .text:

0000000000000000 <popcount8>:
       0:      	adrp	x8, 0x0 <popcount8>
       4:      	dup	v0.4s, w0
       8:      	movi	v2.4s, #0x1
       c:      	ldr	q1, [x8]
      10:      	ubfx	w8, w0, #6, #1
      14:      	and	w9, w0, #0x1
      18:      	ubfx	w10, w0, #1, #1
      1c:      	ubfx	w11, w0, #7, #1
      20:      	ushl	v0.4s, v0.4s, v1.4s
      24:      	add	w8, w9, w8
      28:      	add	w8, w8, w11
      2c:      	and	v0.16b, v0.16b, v2.16b
      30:      	addv	s0, v0.4s
      34:      	fmov	w12, s0
      38:      	add	w9, w12, w10
      3c:      	add	w0, w9, w8
      40:      	ret
