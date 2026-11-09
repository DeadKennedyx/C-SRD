
/work/experiments/runs/algorithm-survival-20261109/popcount8-swar-planned/linux/compiler-1-O2/original.o:	file format elf64-littleaarch64

Disassembly of section .text:

0000000000000000 <popcount8>:
       0:      	and	w1, w0, #0xff
       4:      	mov	w2, #0x8                // =8
       8:      	mov	w0, #0x0                // =0
       c:      	nop
      10:      	and	w3, w1, #0x1
      14:      	subs	w2, w2, #0x1
      18:      	add	w0, w0, w3
      1c:      	lsr	w1, w1, #1
      20:      	b.ne	0x10 <popcount8+0x10>
      24:      	ret
