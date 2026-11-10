"""Fail-closed scalar high P-code reconstruction, without reference source.

Schema 1 admits an unconditional expression DAG. Schema 2 requires an explicit
CFG and complete bounded expansion. This adapter and Ghidra remain trusted
interpretations, not verified binary lifters. Unsupported is never protection.
"""
import re

from pcode_values import Builder, Unsupported
from pcode_cfg import Graph, LIMITS


def reconstruct(export, result_offset=0, *, metrics=None):
    try:
        return _reconstruct(export, result_offset, {} if metrics is None else metrics)
    except Unsupported:
        raise
    except (KeyError, TypeError, ValueError, IndexError) as error:
        raise Unsupported(f"malformed or unresolved high P-code: {error}") from error


def _reconstruct(export, result_offset, metrics):
    name, arity = export["function"], export["arity"]
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name) or type(arity) is not int or not 1 <= arity <= 4:
        raise Unsupported("interface outside bounded protocol")
    schema = export.get("schema_version", 1)
    if type(schema) is not int or schema not in (1, 2):
        raise Unsupported("unknown P-code export schema")
    metrics.update(export_schema=schema, mode="cfg" if schema == 2 else "dag",
                   evaluated_operations=0, emitted_statements=0, block_expansions=0,
                   max_path_block_entries=0, terminal_paths=0, constant_branches=0, symbolic_branches=0)
    graph, builder = Graph(export), Builder(metrics)
    if schema == 2:
        graph.cfg(export)
        result = graph.expand(builder, metrics)
    else:
        returns = [o for o in graph.ops if o["opcode"] == "RETURN"]
        if len(returns) != 1:
            raise Unsupported("legacy export requires one return")
        if any(o["opcode"] in ("BRANCH", "CBRANCH", "MULTIEQUAL") for o in graph.ops):
            raise Unsupported("control flow requires schema-2 block metadata")
        values, visiting = graph.initial.copy(), set()

        def expression(i):
            if i in values:
                return values[i]
            if i in visiting or len(visiting) >= LIMITS["dag_depth"]:
                raise Unsupported("cyclic graph or expression depth budget exceeded")
            if i not in graph.definitions:
                raise Unsupported("unresolved non-parameter input")
            visiting.add(i)
            op = graph.ops[graph.definitions[i]]
            value = builder.operation(op["opcode"], graph.width(i), [expression(v) for v in op["inputs"]])
            visiting.remove(i)
            values[i] = value
            return value

        result = expression(returns[0]["inputs"][1])
        metrics["terminal_paths"] = 1
    expression = result.atom
    if result_offset:
        expression = f"({expression} + {result_offset & 0xffffffff}u)"
    lines = builder.lines + [f"    (void)p{i};" for i in range(arity)]
    parameters = ", ".join(f"unsigned int p{i}" for i in range(arity))
    source = f"unsigned int {name}({parameters}) {{\n" + "\n".join(lines) + f"\n    return {expression};\n}}\n"
    if len(source.encode()) > LIMITS["generated_bytes"]:
        raise Unsupported("generated source budget exceeded")
    metrics["generated_bytes"] = len(source.encode())
    return source
