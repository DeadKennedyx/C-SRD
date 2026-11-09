
/Users/admin/C-SRD/experiments/runs/algorithm-survival-20261109/popcount8-serial-planned/macos/compiler-0-O2/candidate.o:	file format mach-o arm64

Disassembly of section __TEXT,__text:

0000000000000000 <ltmp0>:
       0:      	tst	w0, #0x1
       4:      	mov	w8, #0x75c1             ; =30145
       8:      	movk	w8, #0xd0f0, lsl #16
       c:      	csel	w8, w8, wzr, ne
      10:      	tst	w0, #0x2
      14:      	mov	w9, #0xa03b             ; =41019
      18:      	movk	w9, #0xf771, lsl #16
      1c:      	mov	w10, #0x2a7a            ; =10874
      20:      	movk	w10, #0x2681, lsl #16
      24:      	csel	w9, w10, w9, eq
      28:      	add	w8, w9, w8
      2c:      	ubfx	w9, w0, #2, #1
      30:      	mov	w10, #0x9a41            ; =39489
      34:      	movk	w10, #0x2b1c, lsl #16
      38:      	dup.4s	v0, w0
      3c:      	adrp	x11, 0x0 <ltmp0>
      40:      	ldr	q1, [x11]
      44:      	ushl.4s	v0, v0, v1
      48:      	movi.4s	v1, #0x1
      4c:      	and.16b	v0, v0, v1
      50:      	ubfx	w11, w0, #7, #1
      54:      	addv.4s	s0, v0
      58:      	fmov	w12, s0
      5c:      	add	w11, w12, w11
      60:      	madd	w8, w8, w10, w9
      64:      	mov	w9, #0xd306             ; =54022
      68:      	movk	w9, #0x624e, lsl #16
      6c:      	add	w8, w8, w9
      70:      	add	w0, w8, w11
      74:      	ret
