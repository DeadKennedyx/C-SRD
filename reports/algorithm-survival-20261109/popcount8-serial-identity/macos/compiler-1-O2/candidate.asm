
/Users/admin/C-SRD/experiments/runs/algorithm-survival-20261109/popcount8-serial-identity/macos/compiler-1-O2/candidate.o:	file format mach-o arm64

Disassembly of section __TEXT,__text:

0000000000000000 <ltmp0>:
       0:      	ubfx	x1, x0, #2, #1
       4:      	ubfx	x2, x0, #1, #1
       8:      	add	w2, w2, w1
       c:      	ubfx	x1, x0, #4, #1
      10:      	add	w2, w2, w1
      14:      	ubfx	x1, x0, #6, #1
      18:      	add	w2, w2, w1
      1c:      	ubfx	x3, x0, #7, #1
      20:      	and	w1, w0, #0x1
      24:      	add	w1, w1, w3
      28:      	ubfx	x3, x0, #3, #1
      2c:      	add	w1, w1, w3
      30:      	ubfx	x0, x0, #5, #1
      34:      	add	w0, w1, w0
      38:      	add	w0, w2, w0
      3c:      	ret
