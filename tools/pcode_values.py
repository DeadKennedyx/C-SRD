"""Total unsigned scalar P-code rules shared by DAG and CFG reconstruction.

Values have explicit bit widths. Known values are exact constants, never samples
or solver guesses. Generated C uses unsigned int on the supplied 32-bit ABI.
"""
from dataclasses import dataclass


class Unsupported(ValueError):
    pass


UNARY = {"COPY", "CAST", "INT_ZEXT", "INT_SEXT", "INT_NEGATE", "INT_2COMP", "BOOL_NEGATE"}
BINARY = {"INT_ADD": "+", "INT_SUB": "-", "INT_MULT": "*", "INT_AND": "&",
          "INT_OR": "|", "INT_XOR": "^", "INT_EQUAL": "==", "INT_NOTEQUAL": "!=",
          "INT_LESS": "<", "INT_LESSEQUAL": "<="}
COMPARE = {"INT_EQUAL", "INT_NOTEQUAL", "INT_LESS", "INT_LESSEQUAL"}
COUNTED = {"INT_LEFT", "INT_RIGHT", "INT_SRIGHT", "SUBPIECE"}
SCALAR = UNARY | set(BINARY) | COUNTED | {"PIECE"}
WIDTHS = tuple(range(8, 129, 8))


def shape(code, bits, inputs):
    """Validate native instruction types even when its block is not executed."""
    if code not in SCALAR:
        raise Unsupported(f"unsupported P-code operation: {code}")
    if len(inputs) != (1 if code in UNARY else 2):
        raise Unsupported("unexpected operation arity")
    data_widths = inputs[:1] if code in COUNTED else inputs
    if bits not in WIDTHS or any(w not in WIDTHS for w in data_widths):
        raise Unsupported("unsupported scalar data width")
    if code in BINARY:
        if inputs[0] != inputs[1] or bits != (8 if code in COMPARE else inputs[0]):
            raise Unsupported("binary input/output widths differ")
    elif code in ("COPY", "CAST", "INT_NEGATE", "INT_2COMP", "INT_LEFT", "INT_RIGHT", "INT_SRIGHT"):
        if bits != inputs[0]:
            raise Unsupported("scalar input/output widths differ")
    elif code in ("INT_ZEXT", "INT_SEXT") and bits < inputs[0]:
        raise Unsupported("invalid extension")
    elif code == "BOOL_NEGATE" and (bits != 8 or inputs[0] != 8):
        raise Unsupported("boolean operation requires byte values")
    elif code == "SUBPIECE" and bits > inputs[0]:
        raise Unsupported("subpiece cannot widen a value")
    elif code == "PIECE" and bits != sum(inputs):
        raise Unsupported("piece widths must sum to output width")
    if code in COUNTED and inputs[1] not in (8, 16, 32, 64):
        raise Unsupported("unsupported constant count width")


@dataclass(frozen=True)
class Value:
    bits: int
    atom: str
    known: int | None = None
    parts: tuple = ()  # least-significant first; each stored in unsigned int


def literal(bits, number):
    if not 0 <= number < (1 << bits):
        raise Unsupported("constant does not fit its storage width")
    if bits > 32:
        return Value(bits, "", number, tuple(literal(min(32, bits-i), (number >> i) & ((1 << min(32, bits-i))-1))
                                            for i in range(0, bits, 32)))
    return Value(bits, str(number) + "u", number)


class Builder:
    def __init__(self, metrics):
        self.lines = []
        self.metrics = metrics
        self.serial = 0

    def emit(self, bits, expression):
        if not 0 < bits <= 32:
            raise Unsupported("C scalar storage must fit unsigned int")
        count = 1 + (bits < 32)
        if len(self.lines) + count > 16384:
            raise Unsupported("emitted statement budget exceeded")
        name = "v" + str(self.serial)
        self.serial += 1
        self.lines.append(f"    unsigned int {name} = {expression};")
        if bits < 32:
            self.lines.append(f"    {name} = {name} & {(1 << bits) - 1}u;")
        self.metrics["emitted_statements"] = len(self.lines)
        return Value(bits, name)

    def operation(self, code, bits, args):
        if code.startswith("NEON_"):
            from pcode_vector import shape as vector_shape, operation as vector_operation
            vector_shape(code, bits, [a.bits for a in args])
        else:
            shape(code, bits, [a.bits for a in args])
        self.metrics["evaluated_operations"] += 1
        if self.metrics["evaluated_operations"] > 65536:
            raise Unsupported("evaluated operation budget exceeded")
        if code.startswith("NEON_"):
            return vector_operation(self, code, bits, args)
        if bits > 32 or any(a.bits > 32 for a in (args[:1] if code in COUNTED else args)) or code == "PIECE":
            from pcode_wide import operation
            return operation(self, code, bits, args)
        return self.scalar(code, bits, args)

    def scalar(self, code, bits, args):
        """Internal u32 lowering; original-operation counts exclude helper steps."""
        a, av = args[0].atom, args[0].known
        if code in COUNTED:
            count = args[1].known
            if count is None:
                raise Unsupported("nonconstant shift or subpiece offset")
            shift = count * (8 if code == "SUBPIECE" else 1)
            if code == "SUBPIECE" and shift + bits > args[0].bits:
                raise Unsupported("subpiece extends outside input")
            if code == "INT_SRIGHT":
                sign = 1 << (bits - 1)
                if av is not None:
                    signed = av - (1 << bits) if av & sign else av
                    number = (-1 if signed < 0 else 0) if shift >= bits else signed >> shift
                    return literal(bits, number & ((1 << bits) - 1))
                if shift == 0:
                    return args[0]
                fill = f"(0u - ({a} >> {bits-1}u))"
                if shift >= bits:
                    return self.emit(bits, fill)
                mask = ((1 << bits) - 1) ^ ((1 << (bits-shift)) - 1)
                return self.emit(bits, f"(({a} >> {shift}u) | ({fill} & {mask}u))")
            if shift >= args[0].bits:
                return literal(bits, 0)
            if av is not None:
                number = av << shift if code == "INT_LEFT" else av >> shift
                return literal(bits, number & ((1 << bits) - 1))
            return self.emit(bits, f"({a} {'<<' if code == 'INT_LEFT' else '>>'} {shift}u)")
        if code in BINARY:
            b, bv = args[1].atom, args[1].known
            if code == "INT_MULT" and av is None and bv is None:
                raise Unsupported("general multiplication outside source verifier")
            if av is not None and bv is not None:
                number = {"INT_ADD": lambda: av + bv, "INT_SUB": lambda: av - bv,
                          "INT_MULT": lambda: av * bv, "INT_AND": lambda: av & bv,
                          "INT_OR": lambda: av | bv, "INT_XOR": lambda: av ^ bv,
                          "INT_EQUAL": lambda: int(av == bv), "INT_NOTEQUAL": lambda: int(av != bv),
                          "INT_LESS": lambda: int(av < bv), "INT_LESSEQUAL": lambda: int(av <= bv)}[code]()
                return literal(bits, number & ((1 << bits) - 1))
            return self.emit(bits, f"({a} {BINARY[code]} {b})")
        if code in ("COPY", "CAST", "INT_ZEXT"):
            return Value(bits, a, av)
        sign = 1 << (args[0].bits - 1)
        if av is not None:
            number = {"INT_SEXT": lambda: (av ^ sign) - sign,
                      "INT_NEGATE": lambda: ~av, "INT_2COMP": lambda: -av,
                      "BOOL_NEGATE": lambda: int(av == 0)}[code]()
            return literal(bits, number & ((1 << bits) - 1))
        expression = {"INT_SEXT": f"(({a} ^ {sign}u) - {sign}u)",
                      "INT_NEGATE": f"(~{a})", "INT_2COMP": f"(0u - {a})",
                      "BOOL_NEGATE": f"({a} == 0u)"}[code]
        return self.emit(bits, expression)

    def select(self, condition, yes, no):
        # Internal path composition, never an invented accepted P-code opcode.
        if yes.bits != 32 or no.bits != 32 or condition.bits != 8:
            raise Unsupported("invalid path result or condition width")
        if condition.known is not None:
            return yes if condition.known else no
        return self.emit(32, f"(({condition.atom} != 0u) ? {yes.atom} : {no.atom})")
