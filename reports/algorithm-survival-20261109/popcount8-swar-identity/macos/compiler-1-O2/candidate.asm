
/Users/admin/C-SRD/experiments/runs/algorithm-survival-20261109/popcount8-swar-identity/macos/compiler-1-O2/candidate.o:	file format mach-o arm64

Disassembly of section __TEXT,__text:

0000000000000000 <ltmp0>:
       0:      	mov	w2, #0x55               ; =85
       4:      	and	w1, w0, #0xff
       8:      	and	w0, w2, w0, lsr #1
       c:      	mov	w2, #0x33               ; =51
      10:      	sub	w1, w1, w0
      14:      	and	w0, w2, w1, lsr #2
      18:      	and	w1, w1, w2
      1c:      	add	w0, w0, w1
      20:      	add	w0, w0, w0, lsr #4
      24:      	and	w0, w0, #0xf
      28:      	ret
