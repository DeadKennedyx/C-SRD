
/Users/admin/C-SRD/experiments/runs/algorithm-survival-20261109/popcount8-serial-planned/macos/compiler-1-O2/candidate.o:	file format mach-o arm64

Disassembly of section __TEXT,__text:

0000000000000000 <ltmp0>:
       0:      	mov	w3, #0x5fbb             ; =24507
       4:      	mov	w5, #0xf066             ; =61542
       8:      	movk	w3, #0xf671, lsl #16
       c:      	movk	w5, #0x8d49, lsl #16
      10:      	eor	w1, w0, w3
      14:      	sub	w4, w3, #0x77
      18:      	eor	w0, w0, #0xff
      1c:      	and	w1, w1, w4
      20:      	and	w0, w0, w3
      24:      	add	w4, w4, #0x76
      28:      	eor	w1, w1, w0
      2c:      	eor	x2, x1, #0x10
      30:      	eor	x0, x1, #0x20
      34:      	eor	w5, w5, w1, lsr #1
      38:      	ubfx	x0, x0, #5, #1
      3c:      	ubfx	x2, x2, #4, #1
      40:      	add	w2, w2, w0
      44:      	eor	x0, x1, #0x80
      48:      	ubfx	x0, x0, #7, #1
      4c:      	and	w5, w5, w4
      50:      	add	w2, w2, w0
      54:      	mov	w0, #0xafdc             ; =45020
      58:      	movk	w0, #0x7b38, lsl #16
      5c:      	eor	w0, w0, w1, lsr #1
      60:      	bic	w0, w3, w0
      64:      	eor	w0, w0, w5
      68:      	eor	x5, x1, #0x8
      6c:      	add	w2, w2, w0
      70:      	ubfx	x5, x5, #3, #1
      74:      	ubfx	x0, x1, #2, #1
      78:      	add	w0, w0, w5
      7c:      	ubfx	x5, x1, #6, #1
      80:      	add	w0, w0, w5
      84:      	eor	w5, w1, w4
      88:      	bic	w3, w3, w5
      8c:      	and	w1, w1, w4
      90:      	eor	w3, w3, w1
      94:      	add	w0, w0, w3
      98:      	add	w0, w2, w0
      9c:      	ret
