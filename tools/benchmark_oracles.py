"""Independent specification oracles for the rich corpus, used ONLY by graders.

These implementations are not available as inference inputs to effort workers.
Python integer arithmetic makes truncation explicit. CRC uses the separately
maintained zlib library. Other oracles implement the stated mathematical contract;
they are not themselves formally verified or full application implementations.
"""
import itertools
import random
import zlib

MASK = (1 << 32) - 1


def crc32_byte(state, byte):
    return zlib.crc32(bytes([byte & 255]), state) & MASK


def jenkins_word(state, word):
    value = state
    for byte in word.to_bytes(4, "little"):
        value = ((value + byte) * 1025) & MASK
        value ^= value // 64
    value = (9 * value) & MASK
    value ^= value // 2048
    return (32769 * value) & MASK


def morton16(x, y):
    return sum(((x >> bit) & 1) << (2 * bit) | ((y >> bit) & 1) << (2 * bit + 1)
               for bit in range(16))


def rgb_luma8(rgb):
    _, red, green, blue = rgb.to_bytes(4, "big")
    return (77 * red + 150 * green + 29 * blue) // 256


def fletcher16_word(state, word):
    first, second = (state & 255) % 255, ((state >> 8) & 255) % 255
    for byte in word.to_bytes(4, "little"):
        first = (first + byte) % 255
        second = (second + first) % 255
    return first + 256 * second


def internet_checksum(first, second):
    data = first.to_bytes(4, "big") + second.to_bytes(4, "big")
    value = sum(int.from_bytes(data[i:i+2], "big") for i in range(0, 8, 2))
    while value > 65535:
        value = (value % 65536) + value // 65536
    return 65535 - value


def gray_decode32(gray):
    result = 0
    while gray:
        result ^= gray
        gray //= 2
    return result


def fnv1a_word(state, word):
    value = state
    for byte in word.to_bytes(4, "little"):
        value = ((value ^ byte) * 0x01000193) % (1 << 32)
    return value


ORACLES = {f.__name__: f for f in (crc32_byte, jenkins_word, morton16, rgb_luma8,
                                   fletcher16_word, internet_checksum, gray_decode32, fnv1a_word)}


def vectors(arity, seed, count):
    if arity not in (1, 2):
        raise ValueError("rich v1 corpus has only unary/binary interfaces")
    edges = [0, 1, 2, 3, 127, 128, 254, 255, 256, 257, 65534, 65535, 65536,
             0x7fffffff, 0x80000000, MASK-1, MASK, 0x01020304, 0x04030201,
             0x55555555, 0xaaaaaaaa, 0x12345678]
    values = list(itertools.product(edges, repeat=arity))
    for bit in range(32):
        for index in range(arity):
            for base in (0, MASK):
                v = [base] * arity
                v[index] = base ^ (1 << bit)
                values.append(tuple(v))
    rng = random.Random(seed)
    values += [tuple(rng.getrandbits(32) for _ in range(arity)) for _ in range(count)]
    return list(dict.fromkeys(values))
