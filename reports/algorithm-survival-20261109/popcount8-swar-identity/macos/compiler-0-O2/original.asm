
/Users/admin/C-SRD/experiments/runs/algorithm-survival-20261109/popcount8-swar-identity/macos/compiler-0-O2/original.o:	file format mach-o arm64

Disassembly of section __TEXT,__text:

0000000000000000 <ltmp0>:
       0:      	dup.4s	v0, w0
       4:      	adrp	x8, 0x0 <ltmp0>
       8:      	ldr	q1, [x8]
       c:      	ushl.4s	v1, v0, v1
      10:      	adrp	x8, 0x0 <ltmp0>
      14:      	ldr	q2, [x8]
      18:      	ushl.4s	v0, v0, v2
      1c:      	movi.4s	v2, #0x1
      20:      	and.16b	v0, v0, v2
      24:      	and.16b	v1, v1, v2
      28:      	add.4s	v0, v1, v0
      2c:      	addv.4s	s0, v0
      30:      	fmov	w0, s0
      34:      	ret
