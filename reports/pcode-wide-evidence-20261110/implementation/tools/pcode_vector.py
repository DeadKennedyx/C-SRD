"""Three explicitly modeled AArch64 NEON operations and immutable constants.

Only schema-3, little-endian AArch64 exports from pinned Ghidra 12.2 may supply
these facts. Names come from the exported language table, not guessed user-op
numbers. No arbitrary call, mutable memory, or dynamic vector shift is admitted.
"""
from pcode_values import Value, Unsupported, literal
from pcode_wide import op, pack, slice_word, parts, shift_value

VECTOR = {"NEON_ext", "NEON_rev64", "NEON_ushl"}


def environment(export):
    if (export.get("schema_version") != 3 or export.get("language") != "AARCH64:LE:64:v8A" or
            export.get("ghidra_version") != "12.2" or export.get("memory_model") != "immutable-mapped-constants-v1"):
        raise Unsupported("vector/constant model requires pinned schema-3 AArch64 little-endian export")


def readonly_value(export, node):
    environment(export)
    if "parameter" in node or "constant" in node or node.get("input") is not True:
        raise Unsupported("read-only snapshot must be a non-parameter memory input")
    snapshot = node["readonly"]
    if not isinstance(snapshot, dict) or any(snapshot.get(k) is not v for k, v in
            {"read": True, "write": False, "initialized": True, "relocations": False}.items()) or type(snapshot.get("execute")) is not bool:
        raise Unsupported("mutable, uninitialized, relocated or malformed memory is not a constant")
    if snapshot.get("byte_order") != "little" or snapshot.get("address") != node.get("storage"):
        raise Unsupported("snapshot address/endianness differs from the model")
    data = snapshot.get("bytes_hex")
    if not isinstance(data, str) or len(data) != 2*node["size"] or any(c not in "0123456789abcdef" for c in data):
        raise Unsupported("invalid read-only snapshot bytes")
    addresses = [snapshot.get(k) for k in ("block_start", "address", "block_end")]
    if any(not isinstance(s, str) or not s or len(s) > 16 or any(c not in "0123456789abcdef" for c in s) for s in addresses):
        raise Unsupported("snapshot must use default 64-bit memory-space addresses")
    start, address, end = (int(s, 16) for s in addresses)
    if not start <= address <= address+node["size"]-1 <= end:
        raise Unsupported("snapshot crosses its read-only block")
    return literal(node["size"]*8, int.from_bytes(bytes.fromhex(data), "little"))


def userop_name(export, operation, initial):
    environment(export)
    inputs = operation["inputs"]
    identifier = initial.get(inputs[0]) if inputs else None
    if identifier is None or identifier.known is None or identifier.bits != 32:
        raise Unsupported("user-op identifier must be an explicit 32-bit constant")
    table = export.get("userops")
    name = table.get(str(identifier.known)) if isinstance(table, dict) else None
    if name not in VECTOR:
        raise Unsupported("unsupported or unnamed AArch64 user operation: " + str(name))
    return name


def shape(name, bits, widths):
    count = {"NEON_ext": 4, "NEON_rev64": 2, "NEON_ushl": 3}.get(name)
    if count is None or len(widths) != count or bits not in (64, 128) or widths[0] != bits:
        raise Unsupported("invalid vector operation, arity or width")
    if name in ("NEON_ext", "NEON_ushl") and widths[1] != bits:
        raise Unsupported("vector operand widths differ")
    if any(w != 8 for w in widths[2 if name in ("NEON_ext", "NEON_ushl") else 1:]):
        raise Unsupported("vector lane/count metadata must have byte storage")


def assemble(builder, bits, chunks):
    # Ordered 8/16/32-bit lane fragments; caller supplies a complete bit stream.
    words, accumulated, position = [], literal(32, 0), 0
    for value in chunks:
        if value.bits > 32 or position+value.bits > 32:
            raise Unsupported("vector fragment crosses internal word boundary")
        shifted = op(builder, "INT_LEFT", value, literal(32, position)) if position else value
        accumulated = op(builder, "INT_OR", accumulated, shifted)
        position += value.bits
        if position == 32:
            words.append(accumulated); accumulated, position = literal(32, 0), 0
    if position or len(words)*32 != bits:
        raise Unsupported("incomplete vector reconstruction")
    return pack(builder, bits, words)


def operation(builder, name, bits, args):
    shape(name, bits, [a.bits for a in args])
    lane = args[-1].known
    if lane not in (1, 2, 4, 8):
        raise Unsupported("vector lane size must be a supported exact byte constant")
    a = args[0]
    if name == "NEON_ext":
        offset = args[2].known
        if lane != 1 or offset is None or not 0 <= offset < bits//8:
            raise Unsupported("EXT requires a valid constant byte offset and byte lanes")
        b, size = args[1], bits//8
        chunks = [slice_word(builder, a if i+offset < size else b, ((i+offset) % size)*8, 8) for i in range(size)]
        return assemble(builder, bits, chunks)
    if name == "NEON_rev64":
        if lane == 8:
            raise Unsupported("REV64 lane must be smaller than its 64-bit block")
        width, lanes = lane*8, 8//lane
        chunks = [slice_word(builder, a, (i//lanes*lanes + lanes-1-i%lanes)*width, width) for i in range(bits//width)]
        return assemble(builder, bits, chunks)
    counts = args[1]
    if counts.known is None:
        raise Unsupported("dynamic vector shift counts are outside the bounded model")
    chunks = []
    width = lane*8
    for start in range(0, bits, width):
        byte = (counts.known >> start) & 255
        amount = byte-256 if byte >= 128 else byte
        component = (slice_word(builder, a, start, width) if width <= 32 else
                     pack(builder, 64, [slice_word(builder, a, start, 32), slice_word(builder, a, start+32, 32)]))
        shifted = shift_value(builder, component, abs(amount), left=amount >= 0)
        chunks.extend(parts(shifted))
    return assemble(builder, bits, chunks)
