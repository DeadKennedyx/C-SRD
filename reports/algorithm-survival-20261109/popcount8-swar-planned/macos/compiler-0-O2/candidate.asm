
/Users/admin/C-SRD/experiments/runs/algorithm-survival-20261109/popcount8-swar-planned/macos/compiler-0-O2/candidate.o:	file format mach-o arm64

Disassembly of section __TEXT,__text:

0000000000000000 <ltmp0>:
       0:      	mov	w8, #0x55               ; =85
       4:      	and	w8, w8, w0, lsr #1
       8:      	mov	w9, #0x33               ; =51
       c:      	sub	w8, w0, w8
      10:      	and	w10, w8, w9
      14:      	and	w8, w9, w8, lsr #2
      18:      	add	w8, w8, w10
      1c:      	add	w8, w8, w8, lsr #4
      20:      	and	w0, w8, #0xf
      24:      	ret
