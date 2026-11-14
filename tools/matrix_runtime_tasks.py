"""Prespecified known-intermediate tasks; used by calibration and grading only.

These are implementation-independent numerical labels, not source locations or
encoding parameters. Their existence in another implementation is not assumed.
Full return oracles are independently maintained in benchmark_oracles.py.
"""
import random

from benchmark_oracles import ORACLES, MASK

VERSION = "rich-runtime-values-v1"
ARITIES = {"crc32_byte": 2, "jenkins_word": 2, "morton16": 2, "rgb_luma8": 1}


def targets(case, vector):
    if case not in ARITIES or len(vector) != ARITIES[case]:
        raise ValueError("unknown runtime task or interface")
    if any(type(x) is not int or not 0 <= x <= MASK for x in vector):
        raise ValueError("u32 input required")
    if case == "crc32_byte":
        value = MASK ^ vector[0] ^ (vector[1] & 255)
        labels = {"injected_crc": value}
        for _ in range(4):
            value = (value // 2) ^ (0xedb88320 if value % 2 else 0)
        labels["crc_after_four_rounds"] = value
    elif case == "jenkins_word":
        value = vector[0]
        labels = {}
        for index, byte in enumerate(vector[1].to_bytes(4, "little")):
            value = ((value + byte) * 1025) & MASK
            value ^= value // 64
            if index == 0:
                labels["hash_after_first_byte"] = value
        labels["hash_before_finalization"] = value
    elif case == "morton16":
        labels = {"spread_"+name: sum(((value >> bit) & 1) << (2*bit) for bit in range(16))
                  for name, value in zip(("x", "y"), vector)}
    else:
        _, red, green, blue = vector[0].to_bytes(4, "big")
        labels = {"red_component": red, "weighted_sum": 77*red + 150*green + 29*blue}
    # Public output is a visibility control, not an internal-protection success.
    return {"intermediates": labels, "public_return": ORACLES[case](*vector)}


def vectors(case, seed, training=8, heldout=12):
    if case not in ARITIES or training < 8 or heldout < 8:
        raise ValueError("known task and at least eight inputs per split required")
    arity = ARITIES[case]
    # Frozen calibration covers parity and individual input bytes. Random values
    # supplement this basis; held-out labels never select a location or model.
    basis = [(0,), (1,), (0x100,), (0x10000,), (0xffffff,), (MASK,)] if arity == 1 else [
        (0, 0), (1, 0), (0, 1), (16, 0), (0, 16), (MASK, MASK)]
    rng = random.Random(seed)
    used = set(basis)
    train = list(basis)
    while len(train) < training:
        value = tuple(rng.getrandbits(32) for _ in range(arity))
        if value not in used:
            train.append(value); used.add(value)
    test = []
    for value in (tuple([0x80000000]*arity), tuple([0x7fffffff]*arity)):
        if value not in used:
            test.append(value); used.add(value)
    while len(test) < heldout:
        value = tuple(rng.getrandbits(32) for _ in range(arity))
        if value not in used:
            test.append(value); used.add(value)
    return train, test
