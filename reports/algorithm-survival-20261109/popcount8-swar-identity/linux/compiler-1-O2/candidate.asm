
/work/experiments/runs/algorithm-survival-20261109/popcount8-swar-identity/linux/compiler-1-O2/candidate.o:	file format elf64-littleaarch64

Disassembly of section .text:

0000000000000000 <popcount8>:
       0:      	mov	w3, #0x55               // =85
       4:      	and	w1, w0, #0xff
       8:      	and	w0, w3, w0, lsr #1
       c:      	mov	w2, #0x33               // =51
      10:      	sub	w0, w1, w0
      14:      	and	w1, w0, w2
      18:      	and	w0, w2, w0, lsr #2
      1c:      	add	w0, w0, w1
      20:      	add	w0, w0, w0, lsr #4
      24:      	and	w0, w0, #0xf
      28:      	ret
