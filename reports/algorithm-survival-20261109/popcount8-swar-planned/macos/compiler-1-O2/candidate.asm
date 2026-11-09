
/Users/admin/C-SRD/experiments/runs/algorithm-survival-20261109/popcount8-swar-planned/macos/compiler-1-O2/candidate.o:	file format mach-o arm64

Disassembly of section __TEXT,__text:

0000000000000000 <ltmp0>:
       0:      	mov	w2, #0x5fbb             ; =24507
       4:      	mov	w4, #0xf066             ; =61542
       8:      	movk	w2, #0xf671, lsl #16
       c:      	movk	w4, #0x8d49, lsl #16
      10:      	sub	w3, w2, #0x77
      14:      	eor	w1, w0, w2
      18:      	eor	w0, w0, #0xff
      1c:      	and	w1, w1, w3
      20:      	and	w0, w0, w2
      24:      	add	w5, w3, #0xaa
      28:      	eor	w0, w1, w0
      2c:      	add	w3, w3, #0x44
      30:      	eor	w4, w4, w0, lsr #1
      34:      	eor	w1, w0, w2
      38:      	and	w4, w4, w5
      3c:      	mov	w5, #0xaf88             ; =44936
      40:      	movk	w5, #0x7b38, lsl #16
      44:      	eor	w0, w5, w0, lsr #1
      48:      	mov	w5, #0x855              ; =2133
      4c:      	movk	w5, #0xcbed, lsl #16
      50:      	bic	w0, w2, w0
      54:      	eor	w0, w0, w4
      58:      	sub	w1, w1, w0
      5c:      	mov	w0, #0x57dd             ; =22493
      60:      	eor	w4, w1, w2
      64:      	movk	w0, #0x3d9c, lsl #16
      68:      	eor	w5, w5, w4, lsr #2
      6c:      	eor	w0, w0, w4, lsr #2
      70:      	and	w4, w4, w3
      74:      	and	w5, w5, w3
      78:      	bic	w0, w2, w0
      7c:      	eor	w0, w0, w5
      80:      	mov	w5, #0x33               ; =51
      84:      	eor	w1, w1, w5
      88:      	bic	w2, w2, w1
      8c:      	eor	w2, w2, w4
      90:      	add	w0, w0, w2
      94:      	add	w0, w0, w0, lsr #4
      98:      	and	w0, w0, #0xf
      9c:      	ret
