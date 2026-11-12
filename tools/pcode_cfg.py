"""Validated high P-code graphs and exhaustive, bounded control-flow expansion."""
from pcode_values import SCALAR, COUNTED, WIDTHS, Unsupported, Value, literal, shape
from pcode_vector import readonly_value, userop_name, shape as vector_shape


LIMITS = {"nodes": 4096, "operations": 2048, "blocks": 256, "path_block_entries": 64,
          "block_expansions": 1024, "terminal_paths": 64, "evaluated_operations": 65536,
          "emitted_statements": 16384, "generated_bytes": 1048576, "dag_depth": 128}
CONTROL = {"BRANCH", "CBRANCH", "RETURN"}


def index(value, size, what):
    if type(value) is not int or not 0 <= value < size:
        raise Unsupported(f"invalid {what} index")
    return value


class Graph:
    def __init__(self, export):
        self.nodes, self.ops = export["nodes"], export["operations"]
        if not isinstance(self.nodes, list) or not isinstance(self.ops, list):
            raise Unsupported("nodes and operations must be lists")
        if len(self.nodes) > LIMITS["nodes"] or len(self.ops) > LIMITS["operations"]:
            raise Unsupported("P-code budget exceeded")
        self.definitions, self.initial, self.userops = {}, {}, {}
        for i, node in enumerate(self.nodes):
            size = node["size"]
            if type(size) is not int or not 1 <= size <= 16:
                raise Unsupported("unsupported varnode storage width")
            if "readonly" in node:
                self.initial[i] = readonly_value(export, node)
            elif "constant" in node:
                number = node["constant"]
                if not isinstance(number, str) or not number.isascii() or not number.isdecimal() or len(number) > 39:
                    raise Unsupported("invalid unsigned decimal constant")
                if "parameter" in node or node.get("input", False):
                    raise Unsupported("constant is also an input")
                self.initial[i] = literal(size * 8, int(number))
            elif "parameter" in node:
                slot = index(node["parameter"], export["arity"], "parameter")
                if size != 4 or node.get("input") is not True:
                    raise Unsupported("parameter storage does not match supplied u32 interface")
                self.initial[i] = Value(32, "p" + str(slot))
        for oi, op in enumerate(self.ops):
            code, inputs = op["opcode"], op["inputs"]
            if not isinstance(inputs, list):
                raise Unsupported("operation inputs must be a list")
            for v in inputs:
                index(v, len(self.nodes), "varnode")
            if code == "CALLOTHER":
                self.userops[oi] = userop_name(export, op, self.initial)
            elif code not in SCALAR | CONTROL | {"MULTIEQUAL"}:
                raise Unsupported(f"unsupported P-code operation: {code}")
            if "output" in op:
                out = index(op["output"], len(self.nodes), "varnode")
                if out in self.definitions or out in self.initial or self.nodes[out].get("input"):
                    raise Unsupported("multiple definitions or assignment to an input/constant")
                self.definitions[out] = oi
            if code in CONTROL:
                if "output" in op or len(inputs) != (1 if code == "BRANCH" else 2):
                    raise Unsupported("invalid control operation interface")
                if code == "RETURN" and self.width(inputs[1]) != 32:
                    raise Unsupported("return is not u32")
                if code == "CBRANCH" and self.width(inputs[1]) != 8:
                    raise Unsupported("branch condition is not a boolean byte")
            else:
                if "output" not in op:
                    raise Unsupported("missing data operation output")
                bits = self.width(op["output"])
                if code == "CALLOTHER":
                    vector_shape(self.userops[oi], bits, [self.width(v) for v in inputs[1:]])
                elif code == "MULTIEQUAL":
                    if not inputs or bits not in WIDTHS or any(self.width(v) != bits for v in inputs):
                        raise Unsupported("invalid merge widths or arity")
                else:
                    shape(code, bits, [self.width(v) for v in inputs])
                    if code in COUNTED:
                        count = self.initial.get(inputs[1])
                        if count is None or count.known is None:
                            raise Unsupported("nonconstant shift or subpiece offset")
                        if code == "SUBPIECE" and count.known * 8 + bits > self.width(inputs[0]):
                            raise Unsupported("subpiece extends outside input")

    def width(self, i):
        return self.nodes[i]["size"] * 8

    def cfg(self, export):
        records = export["blocks"]
        if not isinstance(records, list) or not 1 <= len(records) <= LIMITS["blocks"]:
            raise Unsupported("invalid block list or block budget exceeded")
        self.blocks = {}
        positions = {}
        for block in records:
            bid = block["id"]
            if type(bid) is not int or bid < 0 or bid in self.blocks:
                raise Unsupported("invalid or duplicate block id")
            self.blocks[bid] = block
            if any(not isinstance(block[k], list) for k in ("operations", "incoming", "outgoing")):
                raise Unsupported("block operations and edges must be lists")
            ordinary_seen = False
            for pos, oi in enumerate(block["operations"]):
                index(oi, len(self.ops), "operation")
                if oi in positions or self.ops[oi].get("block") != bid:
                    raise Unsupported("operation block membership is inconsistent")
                positions[oi] = (bid, pos)
                op = self.ops[oi]
                if op["opcode"] == "MULTIEQUAL":
                    if ordinary_seen or len(op["inputs"]) != len(block["incoming"]):
                        raise Unsupported("merge must precede instructions and match incoming edges")
                else:
                    ordinary_seen = True
                if op["opcode"] in CONTROL and pos != len(block["operations"]) - 1:
                    raise Unsupported("control operation is not last in block")
            last = self.ops[block["operations"][-1]]["opcode"] if block["operations"] else None
            degree = {"CBRANCH": 2, "RETURN": 0}.get(last, 1)
            if len(block["outgoing"]) != degree:
                raise Unsupported("terminator and successor count disagree")
        if len(positions) != len(self.ops):
            raise Unsupported("unassigned P-code operation")
        entry = export["entry_block"]
        if type(entry) is not int or entry not in self.blocks or self.blocks[entry]["incoming"]:
            raise Unsupported("entry must be a known block with no incoming edges")
        self.entry = entry
        for bid, block in self.blocks.items():
            for direction, reverse in (("incoming", "outgoing"), ("outgoing", "incoming")):
                for slot, edge in enumerate(block[direction]):
                    other = edge["block"]
                    if type(other) is not int or other not in self.blocks:
                        raise Unsupported("unknown edge endpoint")
                    peers = self.blocks[other][reverse]
                    rev = index(edge["reverse_index"], len(peers), "reverse edge")
                    if peers[rev] != {"block": bid, "reverse_index": slot}:
                        raise Unsupported("edge reciprocity is inconsistent")
        reachable, pending = set(), [entry]
        while pending:
            bid = pending.pop()
            if bid not in reachable:
                reachable.add(bid)
                pending.extend(e["block"] for e in self.blocks[bid]["outgoing"])
        if reachable != self.blocks.keys():
            raise Unsupported("disconnected or unreachable exported block")
        # Check SSA dominance independently of any constant path pruning. Phi
        # operands must be available on their incoming edge, not at block entry.
        dom = {bid: {entry} if bid == entry else set(reachable) for bid in reachable}
        changed = True
        while changed:
            changed = False
            for bid, block in self.blocks.items():
                if bid == entry:
                    continue
                value = {bid} | set.intersection(*(dom[e["block"]] for e in block["incoming"]))
                if value != dom[bid]:
                    dom[bid], changed = value, True
        for oi, op in enumerate(self.ops):
            bid, pos = positions[oi]
            code = op["opcode"]
            inputs = op["inputs"][1:] if code in CONTROL | {"CALL"} else op["inputs"]
            for slot, v in enumerate(inputs):
                if v in self.initial:
                    continue
                if v not in self.definitions:
                    raise Unsupported("unresolved non-parameter input")
                dbid, dpos = positions[self.definitions[v]]
                target = self.blocks[bid]["incoming"][slot]["block"] if code == "MULTIEQUAL" else bid
                if dbid not in dom[target] or (code != "MULTIEQUAL" and dbid == bid and dpos >= pos):
                    raise Unsupported("definition does not dominate its use or incoming edge")

    def expand(self, builder, metrics):
        def walk(bid, incoming, environment, depth):
            metrics["block_expansions"] += 1
            metrics["max_path_block_entries"] = max(metrics["max_path_block_entries"], depth)
            if depth > LIMITS["path_block_entries"] or metrics["block_expansions"] > LIMITS["block_expansions"]:
                raise Unsupported("complete control-flow expansion exceeds block budget")
            block = self.blocks[bid]
            operations = [self.ops[i] for i in block["operations"]]
            # A snapshot is essential for self-loop phi swaps: all merges read
            # the previous edge state before any merge output is assigned.
            merged = {o["output"]: environment[o["inputs"][incoming]] for o in operations
                      if o["opcode"] == "MULTIEQUAL"}
            env = environment.copy()
            for op in operations:
                if "output" in op:
                    env.pop(op["output"], None)
            env.update(merged)
            for op in operations:
                code = op["opcode"]
                if code == "MULTIEQUAL":
                    continue
                if code == "RETURN":
                    metrics["terminal_paths"] += 1
                    if metrics["terminal_paths"] > LIMITS["terminal_paths"]:
                        raise Unsupported("complete control-flow expansion exceeds terminal-path budget")
                    return env[op["inputs"][1]]
                if code in CONTROL:
                    continue
                if code == "CALLOTHER":
                    oi = self.definitions[op["output"]]
                    env[op["output"]] = builder.operation(self.userops[oi], self.width(op["output"]), [env[v] for v in op["inputs"][1:]])
                else:
                    env[op["output"]] = builder.operation(code, self.width(op["output"]), [env[v] for v in op["inputs"]])
            def successor(slot):
                edge = block["outgoing"][slot]
                return walk(edge["block"], edge["reverse_index"], env, depth + 1)
            if operations and operations[-1]["opcode"] == "CBRANCH":
                condition = env[operations[-1]["inputs"][1]]
                if condition.known is not None:
                    metrics["constant_branches"] += 1
                    return successor(int(condition.known != 0))
                metrics["symbolic_branches"] += 1
                no = successor(0)
                yes = successor(1)
                return builder.select(condition, yes, no)
            return successor(0)
        return walk(self.entry, None, self.initial, 1)
