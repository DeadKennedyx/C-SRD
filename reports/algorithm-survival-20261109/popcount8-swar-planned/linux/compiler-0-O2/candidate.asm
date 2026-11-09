
/work/experiments/runs/algorithm-survival-20261109/popcount8-swar-planned/linux/compiler-0-O2/candidate.o:	file format elf64-littleaarch64

Disassembly of section .text:

0000000000000000 <popcount8>:
       0:      	mov	w8, #0x55               // =85
       4:      	and	w9, w0, #0xff
       8:      	and	w8, w8, w0, lsr #1
       c:      	sub	w8, w9, w8
      10:      	mov	w9, #0x33               // =51
      14:      	and	w10, w9, w8, lsr #2
      18:      	and	w8, w8, w9
      1c:      	add	w8, w10, w8
      20:      	add	w8, w8, w8, lsr #4
      24:      	and	w0, w8, #0xf
      28:      	ret
