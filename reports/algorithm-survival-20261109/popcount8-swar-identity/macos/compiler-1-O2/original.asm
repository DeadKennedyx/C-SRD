
/Users/admin/C-SRD/experiments/runs/algorithm-survival-20261109/popcount8-swar-identity/macos/compiler-1-O2/original.o:	file format mach-o arm64

Disassembly of section __TEXT,__text:

0000000000000000 <ltmp0>:
       0:      	sub	sp, sp, #0x10
       4:      	movi.4s	v31, #0x1
       8:      	str	w0, [sp, #0xc]
       c:      	adrp	x0, 0x0 <ltmp0>
      10:      	ldr	b0, [sp, #0xc]
      14:      	ldr	q30, [x0]
      18:      	add	sp, sp, #0x10
      1c:      	dup.4s	v0, v0[0]
      20:      	ushl.4s	v30, v0, v30
      24:      	ushr.4s	v29, v30, #0x4
      28:      	and.16b	v29, v29, v31
      2c:      	and.16b	v31, v30, v31
      30:      	add.4s	v31, v29, v31
      34:      	addv.4s	s31, v31
      38:      	fmov	w0, s31
      3c:      	ret
