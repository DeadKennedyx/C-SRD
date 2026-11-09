
/work/experiments/runs/algorithm-survival-20261109/popcount8-serial-planned/linux/compiler-1-O2/candidate.o:	file format elf64-littleaarch64

Disassembly of section .text:

0000000000000000 <popcount8>:
       0:      	mov	w7, #0x5fbb             // =24507
       4:      	mov	w5, #0xf066             // =61542
       8:      	movk	w7, #0xf671, lsl #16
       c:      	sub	w3, w7, #0x77
      10:      	eor	w1, w0, w7
      14:      	eor	w0, w0, #0xff
      18:      	and	w0, w0, w7
      1c:      	and	w1, w1, w3
      20:      	eor	w1, w1, w0
      24:      	add	w3, w3, #0x76
      28:      	eor	x10, x1, #0x8
      2c:      	eor	x6, x1, #0x10
      30:      	eor	x8, x1, #0x20
      34:      	lsr	w2, w1, #1
      38:      	eor	x9, x1, #0x80
      3c:      	mov	w11, #0xafdc            // =45020
      40:      	eor	w4, w1, w3
      44:      	ubfx	x10, x10, #3, #1
      48:      	ubfx	x0, x1, #2, #1
      4c:      	ubfx	x8, x8, #5, #1
      50:      	movk	w11, #0x7b38, lsl #16
      54:      	ubfx	x6, x6, #4, #1
      58:      	movk	w5, #0x8d49, lsl #16
      5c:      	eor	w5, w2, w5
      60:      	eor	w2, w2, w11
      64:      	add	w6, w6, w8
      68:      	add	w0, w0, w10
      6c:      	ubfx	x8, x1, #6, #1
      70:      	ubfx	x9, x9, #7, #1
      74:      	and	w1, w1, w3
      78:      	bic	w4, w7, w4
      7c:      	and	w3, w5, w3
      80:      	bic	w2, w7, w2
      84:      	add	w0, w0, w6
      88:      	add	w5, w8, w9
      8c:      	eor	w1, w4, w1
      90:      	eor	w2, w2, w3
      94:      	add	w0, w0, w5
      98:      	add	w2, w2, w1
      9c:      	add	w0, w0, w2
      a0:      	ret
