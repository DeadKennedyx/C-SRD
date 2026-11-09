
/work/experiments/runs/algorithm-survival-20261109/popcount8-swar-planned/linux/compiler-1-O2/candidate.o:	file format elf64-littleaarch64

Disassembly of section .text:

0000000000000000 <popcount8>:
       0:      	mov	w2, #0x5fbb             // =24507
       4:      	mov	w6, #0xaf88             // =44936
       8:      	movk	w2, #0xf671, lsl #16
       c:      	sub	w4, w2, #0x77
      10:      	eor	w1, w0, w2
      14:      	eor	w0, w0, #0xff
      18:      	and	w3, w0, w2
      1c:      	and	w0, w1, w4
      20:      	eor	w0, w0, w3
      24:      	mov	w3, #0xf066             // =61542
      28:      	add	w5, w4, #0xaa
      2c:      	movk	w6, #0x7b38, lsl #16
      30:      	lsr	w1, w0, #1
      34:      	movk	w3, #0x8d49, lsl #16
      38:      	eor	w3, w1, w3
      3c:      	eor	w1, w1, w6
      40:      	and	w3, w3, w5
      44:      	bic	w1, w2, w1
      48:      	eor	w1, w1, w3
      4c:      	eor	w0, w0, w2
      50:      	sub	w0, w0, w1
      54:      	mov	w3, #0x855              // =2133
      58:      	eor	w5, w0, w2
      5c:      	mov	w1, #0x33               // =51
      60:      	mov	w6, #0x57dd             // =22493
      64:      	eor	w1, w0, w1
      68:      	lsr	w0, w5, #2
      6c:      	add	w4, w4, #0x44
      70:      	movk	w6, #0x3d9c, lsl #16
      74:      	movk	w3, #0xcbed, lsl #16
      78:      	eor	w3, w0, w3
      7c:      	eor	w0, w0, w6
      80:      	bic	w1, w2, w1
      84:      	and	w5, w5, w4
      88:      	and	w3, w3, w4
      8c:      	bic	w0, w2, w0
      90:      	eor	w1, w1, w5
      94:      	eor	w0, w0, w3
      98:      	add	w0, w0, w1
      9c:      	add	w0, w0, w0, lsr #4
      a0:      	and	w0, w0, #0xf
      a4:      	ret
