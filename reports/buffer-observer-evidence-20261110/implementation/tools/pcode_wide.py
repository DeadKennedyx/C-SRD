"""Lower bounded 8..128-bit P-code integers to unsigned-int components.

Component order is numeric significance, independent of host byte order. This
module does not assign lane semantics to vectors or interpret opaque user ops.
All helpers use total u32 operations; only the public operation is counted as
one P-code operation. Emitted statements still consume the shared budget.
"""
from pcode_values import Value, Unsupported, literal


def word(value):
    if value.bits > 32:
        raise Unsupported("wide value used as a scalar component")
    return Value(32, value.atom, value.known)


def op(builder, code, *args):
    bits = 8 if code in ("INT_EQUAL", "INT_NOTEQUAL", "INT_LESS", "INT_LESSEQUAL") else 32
    if code == "INT_LESS" and args[1].known == 0:
        return literal(8, 0)
    return builder.scalar(code, bits, [word(a) for a in args])


def trim(builder, value, bits):
    if value.known is not None:
        return literal(bits, value.known & ((1 << bits)-1))
    if value.bits <= bits:
        return Value(bits, value.atom)
    value = op(builder, "INT_AND", value, literal(32, (1 << bits)-1))
    return Value(bits, value.atom)


def parts(value):
    return value.parts if value.bits > 32 else (value,)


def pack(builder, bits, values):
    if len(values) != (bits+31)//32:
        raise Unsupported("wide component count mismatch")
    values = tuple(trim(builder, v, min(32, bits-32*i)) for i, v in enumerate(values))
    if all(v.known is not None for v in values):
        return literal(bits, sum(v.known << (32*i) for i, v in enumerate(values)))
    return values[0] if bits <= 32 else Value(bits, "", None, values)


def slice_word(builder, value, start, bits):
    """Extract <=32 bits; out-of-range high bits are zero (internal helper)."""
    if start < 0 or not 0 < bits <= 32:
        raise Unsupported("invalid internal slice")
    if start >= value.bits:
        return literal(bits, 0)
    if value.known is not None:
        return literal(bits, (value.known >> start) & ((1 << bits)-1))
    index, shift = divmod(start, 32)
    chunks = parts(value)
    result = word(chunks[index])
    if shift:
        result = op(builder, "INT_RIGHT", result, literal(32, shift))
    if shift and bits+shift > 32 and index+1 < len(chunks):
        high = op(builder, "INT_LEFT", chunks[index+1], literal(32, 32-shift))
        result = op(builder, "INT_OR", result, high)
    return trim(builder, result, bits)


def sign_fill(builder, value):
    sign = slice_word(builder, value, value.bits-1, 1)
    return op(builder, "INT_SUB", literal(32, 0), sign)


def extend(builder, value, bits, signed=False):
    fill = sign_fill(builder, value) if signed else literal(32, 0)
    result = []
    for start in range(0, bits, 32):
        width = min(32, bits-start)
        chunk = slice_word(builder, value, start, width)
        available = max(0, min(width, value.bits-start))
        if signed and available < width:
            mask = ((1 << width)-1) ^ ((1 << available)-1)
            chunk = op(builder, "INT_OR", chunk, op(builder, "INT_AND", fill, literal(32, mask)))
        result.append(chunk)
    return pack(builder, bits, result)


def shift_value(builder, value, count, left=False, signed=False, output_bits=None):
    bits = value.bits if output_bits is None else output_bits
    result = []
    fill = sign_fill(builder, value) if signed else literal(32, 0)
    for start in range(0, bits, 32):
        width = min(32, bits-start)
        offset = start-count if left else start+count
        if offset < 0:
            chunk = (op(builder, "INT_LEFT", slice_word(builder, value, 0, width+offset), literal(32, -offset))
                     if -offset < width else literal(width, 0))
        else:
            chunk = slice_word(builder, value, offset, width)
        if signed:
            available = max(0, min(width, value.bits-offset))
            if available < width:
                mask = ((1 << width)-1) ^ ((1 << available)-1)
                chunk = op(builder, "INT_OR", chunk, op(builder, "INT_AND", fill, literal(32, mask)))
        result.append(chunk)
    return pack(builder, bits, result)


def add_sub(builder, a, b, subtract=False):
    result, carry = [], literal(32, 0)
    code = "INT_SUB" if subtract else "INT_ADD"
    for av, bv in zip(parts(a), parts(b)):
        partial = op(builder, code, av, bv)
        first = op(builder, "INT_LESS", av, bv) if subtract else op(builder, "INT_LESS", partial, av)
        total = op(builder, code, partial, carry)
        second = op(builder, "INT_LESS", partial, carry) if subtract else op(builder, "INT_LESS", total, partial)
        carry = op(builder, "INT_OR", first, second)
        result.append(total)
    return pack(builder, a.bits, result)


def multiply_constant(builder, value, constant):
    # Schoolbook base-2^16 arithmetic. Each partial fits u32:
    # (B-1)^2 + (B-1) + (B-1) = 2^32-1, including carry and existing digit.
    count = (value.bits+15)//16
    digits = [literal(16, 0) for _ in range(count)]
    for i in range(count):
        av = slice_word(builder, value, 16*i, 16)
        carry = literal(16, 0)
        for j in range(count-i):
            coefficient = literal(32, (constant >> (16*j)) & 65535)
            partial = op(builder, "INT_MULT", av, coefficient)
            partial = op(builder, "INT_ADD", op(builder, "INT_ADD", partial, digits[i+j]), carry)
            digits[i+j] = trim(builder, partial, 16)
            carry = op(builder, "INT_RIGHT", partial, literal(32, 16))
    words = []
    for i in range(0, count, 2):
        chunk = digits[i]
        if i+1 < count:
            chunk = op(builder, "INT_OR", chunk, op(builder, "INT_LEFT", digits[i+1], literal(32, 16)))
        words.append(chunk)
    return pack(builder, value.bits, words)


def operation(builder, code, bits, args):
    a = args[0]
    if code in ("COPY", "CAST"):
        return a
    if code in ("INT_ZEXT", "INT_SEXT"):
        return extend(builder, a, bits, code == "INT_SEXT")
    if code == "PIECE":
        b = args[1]
        high = shift_value(builder, extend(builder, a, bits), b.bits, left=True)
        low = extend(builder, b, bits)
        return pack(builder, bits, [op(builder, "INT_OR", x, y) for x, y in zip(parts(high), parts(low))])
    if code in ("INT_LEFT", "INT_RIGHT", "INT_SRIGHT", "SUBPIECE"):
        count = args[1].known
        if count is None:
            raise Unsupported("nonconstant shift or subpiece offset")
        if code == "SUBPIECE":
            count *= 8
            if count+bits > a.bits:
                raise Unsupported("subpiece extends outside input")
        return shift_value(builder, a, count, left=code == "INT_LEFT", signed=code == "INT_SRIGHT", output_bits=bits)
    if code == "INT_NEGATE":
        return pack(builder, bits, [op(builder, "INT_NEGATE", x) for x in parts(a)])
    if code == "INT_2COMP":
        return add_sub(builder, literal(bits, 0), a, subtract=True)
    b = args[1]
    if code in ("INT_ADD", "INT_SUB"):
        return add_sub(builder, a, b, subtract=code == "INT_SUB")
    if code == "INT_MULT":
        if a.known is None and b.known is None:
            raise Unsupported("general multiplication outside source verifier")
        return multiply_constant(builder, a if b.known is not None else b, b.known if b.known is not None else a.known)
    if code in ("INT_AND", "INT_OR", "INT_XOR"):
        return pack(builder, bits, [op(builder, code, x, y) for x, y in zip(parts(a), parts(b))])
    if code in ("INT_EQUAL", "INT_NOTEQUAL", "INT_LESS", "INT_LESSEQUAL"):
        equal, less = literal(8, 1), literal(8, 0)
        for av, bv in reversed(list(zip(parts(a), parts(b)))):
            lt, eq = op(builder, "INT_LESS", av, bv), op(builder, "INT_EQUAL", av, bv)
            less = op(builder, "INT_OR", less, op(builder, "INT_AND", equal, lt))
            equal = op(builder, "INT_AND", equal, eq)
        if code == "INT_EQUAL": result = equal
        elif code == "INT_NOTEQUAL": result = op(builder, "INT_XOR", equal, literal(32, 1))
        elif code == "INT_LESS": result = less
        else: result = op(builder, "INT_OR", less, equal)
        return trim(builder, result, 8)
    raise Unsupported("unmodeled wide operation: " + code)
