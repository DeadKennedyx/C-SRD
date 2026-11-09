
/work/experiments/runs/algorithm-survival-20261109/popcount8-serial-identity/linux/compiler-1-O2/candidate.o:	file format elf64-littleaarch64

Disassembly of section .text:

0000000000000000 <popcount8>:
       0:      	ubfx	x4, x0, #2, #1
       4:      	ubfx	x3, x0, #7, #1
       8:      	and	w1, w0, #0x1
       c:      	ubfx	x2, x0, #1, #1
      10:      	add	w1, w1, w3
      14:      	add	w2, w2, w4
      18:      	ubfx	x3, x0, #4, #1
      1c:      	ubfx	x4, x0, #3, #1
      20:      	add	w4, w4, w3
      24:      	add	w2, w2, w1
      28:      	ubfx	x3, x0, #5, #1
      2c:      	ubfx	x1, x0, #6, #1
      30:      	add	w2, w2, w4
      34:      	add	w0, w3, w1
      38:      	add	w0, w2, w0
      3c:      	ret
