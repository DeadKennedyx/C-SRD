"""Memory-observer semantics, alias-sensitive controls and fail-closed exports."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from pcode_memory import reconstruct, Unsupported

TOOL = str(Path(sys.argv.pop(1)).resolve())


class Export:
    def __init__(self, readonly=False):
        self.data = {"schema_version": 4, "memory_model": "ordered-u32-buffers-v1", "function": "f",
                     "arity": 3, "parameters": [{"kind": "uint32-buffer", "read_only": readonly},
                                                {"kind": "uint32-buffer", "read_only": False},
                                                {"kind": "uint32", "read_only": False}],
                     "address_space": {"id": 433, "pointer_bytes": 8, "addressable_unit_bytes": 1},
                     "entry_block": 0, "operation_order": "basic-block-live-order",
                     "nodes": [], "operations": [],
                     "blocks": [{"id": 0, "incoming": [], "outgoing": [], "operations": []}]}
        self.p = self.node(8, input=True, parameter=0)
        self.q = self.node(8, input=True, parameter=1)
        self.x = self.node(4, input=True, parameter=2)
        self.space = self.constant(433, 4)
        self.destination = self.constant(0, 8)

    def node(self, size, **fields):
        result = len(self.data["nodes"])
        self.data["nodes"].append({"size": size, **fields})
        return result

    def constant(self, value, size=4):
        return self.node(size, constant=str(value))

    def op(self, code, inputs, size=4):
        output = self.node(size) if size else None
        item = {"opcode": code, "inputs": inputs, "block": 0}
        if output is not None:
            item["output"] = output
        self.data["blocks"][0]["operations"].append(len(self.data["operations"]))
        self.data["operations"].append(item)
        return output

    def load(self, pointer):
        return self.op("LOAD", [self.space, pointer])

    def store(self, pointer, value):
        self.op("STORE", [self.space, pointer, value], size=None)

    def finish(self, value):
        self.op("RETURN", [self.destination, value], size=None)
        return self.data


def snapshot():
    e = Export()
    before = e.load(e.p)
    e.store(e.q, e.x)
    after = e.load(e.p)
    result = e.op("INT_ADD", [before, after])
    return e.finish(result)


def byte_diamond():
    e=Export()
    e.data.update(schema_version=5,memory_model="ordered-byte-buffers-v2")
    e.data["parameters"][0].update(kind="unsigned-char-buffer",element_signed=False)
    masked=e.op("INT_AND",[e.x,e.constant(7)])
    cap=e.constant(3)
    condition=e.op("INT_LESS",[cap,masked],size=1)
    e.op("CBRANCH",[e.destination,condition],size=None)
    first=len(e.data["operations"])
    no=e.op("COPY",[masked]);e.op("BRANCH",[e.destination],size=None)
    second=len(e.data["operations"])
    yes=e.op("COPY",[cap]);e.op("BRANCH",[e.destination],size=None)
    join=len(e.data["operations"])
    merged=e.op("MULTIEQUAL",[no,yes])
    wide=e.op("INT_ZEXT",[merged],size=8)
    pointer=e.op("PTRADD",[e.p,wide,e.constant(1,8)],size=8)
    value=e.op("LOAD",[e.space,pointer],size=1)
    data=e.finish(e.op("INT_ZEXT",[value]))
    def edge(block,reverse):return {"block":block,"reverse_index":reverse}
    ranges=[(0,first),(first,second),(second,join),(join,len(data["operations"]))]
    incoming=[[],[edge(0,0)],[edge(0,1)],[edge(1,0),edge(2,0)]]
    outgoing=[[edge(1,0),edge(2,0)],[edge(3,0)],[edge(3,1)],[]]
    data["blocks"]=[]
    for i,(begin,end) in enumerate(ranges):
        for op in data["operations"][begin:end]:op["block"]=i
        data["blocks"].append({"id":i,"operations":list(range(begin,end)),"incoming":incoming[i],"outgoing":outgoing[i]})
    return data


class MemoryReconstruction(unittest.TestCase):
    def grade(self, reference, candidate, expected="proved-under-model"):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "a.c").write_text(reference + "\n")
            (p / "b.c").write_text(candidate)
            process = subprocess.run([TOOL, "verify", p / "a.c", p / "b.c", "--report", p / "report.json"],
                                     capture_output=True, text=True)
            report = json.loads((p / "report.json").read_text())
            f, = report["functions"]
            self.assertEqual(f["verification"], expected, process.stderr + str(f))
            self.assertEqual(process.returncode, 0 if expected == "proved-under-model" else 3)
            return f

    def test_aliasing_load_snapshots_preserved(self):
        reference = "unsigned int f(unsigned int*p,unsigned int*q,unsigned int x){unsigned int v=p[0];q[0]=x;return v+p[0];}"
        data, metrics = snapshot(), {}
        self.grade(reference, reconstruct(data, metrics=metrics))
        self.assertEqual((metrics["loads"], metrics["stores"]), (2, 1))
        self.assertEqual(metrics["footprint_elements"], {"0": 1, "1": 1})
        self.grade(reference, reconstruct(data, result_offset=1), "counterexample")
        # Move the store after the second load. Valid SSA, wrong with aliases.
        data["operations"][1], data["operations"][2] = data["operations"][2], data["operations"][1]
        self.grade(reference, reconstruct(data), "counterexample")

    def test_byte_dynamic_offset_and_word_alias(self):
        e=Export()
        e.data.update(schema_version=5,memory_model="ordered-byte-buffers-v2")
        e.data["parameters"][0].update(kind="unsigned-char-buffer",element_signed=False)
        idx=e.op("INT_AND",[e.x,e.constant(7)])
        wide=e.op("INT_ZEXT",[idx],size=8)
        pointer=e.op("PTRADD",[e.p,wide,e.constant(1,8)],size=8)
        before=e.load(e.q)
        low=e.op("SUBPIECE",[e.x,e.constant(0)],size=1)
        e.store(pointer,low)
        after=e.load(e.q)
        data=e.finish(e.op("INT_ADD",[before,after]))
        metrics={}
        self.grade("unsigned int f(unsigned char*p,unsigned int*q,unsigned int x){unsigned int b=q[0];p[x&7u]=x;return b+q[0];}",reconstruct(data,metrics=metrics))
        self.assertEqual(metrics["footprint_elements"],{"0":8,"1":1})
        self.grade(reconstruct(data),reconstruct(data,final_store_offset=1),"counterexample")
        # An unbounded offset must not acquire a false range just from clamping.
        data["operations"][0]["inputs"][1]=e.constant(0xffffffff)
        with self.assertRaises(Unsupported): reconstruct(data)

    def test_signed_byte_load_is_raw_before_sign_extension(self):
        e=Export()
        e.data.update(schema_version=5,memory_model="ordered-byte-buffers-v2")
        e.data["parameters"][0].update(kind="signed-char-buffer",element_signed=True)
        raw=e.op("LOAD",[e.space,e.p],size=1)
        value=e.op("INT_SEXT",[raw])
        data=e.finish(value)
        self.grade("unsigned int f(signed char*p,unsigned int*q,unsigned int x){(void)q;(void)x;return (unsigned int)p[0];}",reconstruct(data))

    def test_scalar_diamond_preserves_clamped_index(self):
        data=byte_diamond();metrics={}
        source=reconstruct(data,metrics=metrics)
        self.grade("unsigned int f(unsigned char*p,unsigned int*q,unsigned int x){(void)q;unsigned int i=x&7u;return p[i<=3u?i:3u];}",source)
        self.assertEqual(metrics["scalar_diamonds"],1)
        self.assertEqual(metrics["footprint_elements"]["0"],4)
        legacy=copy.deepcopy(data)
        for block in legacy["blocks"]:
            for direction in ("incoming","outgoing"):
                block[direction]=[e["block"] for e in block[direction]]
        self.grade("unsigned int f(unsigned char*p,unsigned int*q,unsigned int x){(void)q;unsigned int i=x&7u;return p[i<=3u?i:3u];}",reconstruct(legacy))
        # Wrong incoming-phi correspondence changes results on concrete inputs.
        wrong=copy.deepcopy(data)
        phi=next(o for o in wrong["operations"] if o["opcode"]=="MULTIEQUAL")
        phi["inputs"].reverse()
        # This input violates dominance (arm-local definitions on wrong edges).
        with self.assertRaises(Unsupported):reconstruct(wrong)

    def test_diamond_cannot_speculate_effects_or_accept_virtual_opcodes(self):
        data=byte_diamond()
        branch=data["operations"][data["blocks"][1]["operations"][0]]
        phi=next(o for o in data["operations"] if o["opcode"]=="MULTIEQUAL")
        phi["inputs"][0]=branch["inputs"][0]
        # Replace the false arm's copy with a store; its inputs dominate it.
        branch.update(opcode="STORE",inputs=[3,0,2]);branch.pop("output")
        with self.assertRaisesRegex(Unsupported,"effects"):reconstruct(data)
        data=byte_diamond();data["operations"][0]["opcode"]="CSRD_SELECT"
        with self.assertRaises(Unsupported):reconstruct(data)

    def test_stores_survive_constant_return_and_mutations(self):
        e = Export(); e.store(e.p, e.x); e.store(e.q, e.load(e.p))
        data = e.finish(e.constant(19))
        reference = "unsigned int f(unsigned int*p,unsigned int*q,unsigned int x){p[0]=x;q[0]=p[0];return 19u;}"
        self.grade(reference, reconstruct(data))
        proof = self.grade(reference, reconstruct(data, store_offset=1), "counterexample")
        self.assertEqual(proof["proof"]["original_output"], proof["proof"]["candidate_output"])
        self.assertTrue(any(c["original"] != c["candidate"] for c in proof["proof"]["memory_cells"]))

    def test_last_store_control_avoids_cancelling_mutations(self):
        e = Export(); e.store(e.p, e.x)
        negated = e.op("INT_2COMP", [e.load(e.p)])
        e.store(e.p, negated); data = e.finish(e.constant(19))
        original = reconstruct(data)
        # Incrementing both stores cancels: -(x+1)+1 == -x.
        self.grade(original, reconstruct(data, store_offset=1))
        self.grade(original, reconstruct(data, final_store_offset=1), "counterexample")

    def test_pointer_offsets_copy_and_field_offsets(self):
        for opcode in ("PTRADD", "PTRSUB", "INT_ADD", "INT_SUB"):
            e = Export(readonly=True)
            args = [e.p, e.constant(15 if opcode == "PTRADD" else (60 if opcode != "INT_SUB" else (1 << 64)-60), 8)]
            if opcode == "PTRADD": args.append(e.constant(4, 8))
            pointer = e.op(opcode, args, size=8)
            pointer = e.op("COPY", [pointer], size=8)
            result = e.load(pointer)
            e.store(e.q, result)
            self.grade("unsigned int f(const unsigned int*p,unsigned int*q,unsigned int x){(void)x;q[0]=p[15];return p[15];}",
                       reconstruct(e.finish(result)))

    def test_scalar_canonicalization_inside_memory_contract(self):
        for code, constant, expression in (("INT_LEFT", 3, "x*8u"), ("INT_LEFT", 32, "0u"),
                                            ("INT_LEFT", 0xffffffffffffffff, "0u"),
                                            ("INT_NEGATE", None, "4294967295u-x"),
                                            ("INT_2COMP", None, "0u-x")):
            e = Export()
            inputs = [e.x] + ([] if constant is None else [e.constant(constant, 8)])
            result = e.op(code, inputs)
            e.store(e.p, result)
            self.grade(f"unsigned int f(unsigned int*p,unsigned int*q,unsigned int x){{(void)q;p[0]={expression};return p[0];}}",
                       reconstruct(e.finish(result)))

    def test_32_bit_pointer_model(self):
        e = Export()
        pointer = e.op("PTRADD", [e.p, e.constant(15, 8), e.constant(4, 8)], size=8)
        e.store(pointer, e.x)
        data = e.finish(e.load(e.q))
        data["address_space"]["pointer_bytes"] = 4
        for node in data["nodes"]:
            if node["size"] == 8: node["size"] = 4
        self.grade("unsigned int f(unsigned int*p,unsigned int*q,unsigned int x){p[15]=x;return q[0];}", reconstruct(data))

    def test_reject_unknown_memory_and_malformed_graphs(self):
        changes = [
            lambda e: e.update(schema_version=3),
            lambda e: e["address_space"].update(addressable_unit_bytes=2),
            lambda e: e["address_space"].update(pointer_bytes=2),
            lambda e: e["address_space"].update(id=434),
            lambda e: e["parameters"][1].update(read_only=True),
            lambda e: e["nodes"][0].update(size=4),
            lambda e: e["nodes"][0].pop("parameter"),
            lambda e: e["nodes"][3].update(constant="-1"),
            lambda e: e["operations"][0].update(opcode="CALL"),
            lambda e: e["operations"][0].update(inputs=[999]),
            lambda e: e["operations"][0].update(output=0),
            lambda e: e["operations"][1].update(output=7),
            lambda e: e["operations"][1].update(inputs=[3, 2, 2]),
            lambda e: e["operations"][0].update(block=1),
            lambda e: e["blocks"][0].update(outgoing=[1]),
            lambda e: e["blocks"][0]["operations"].reverse(),
            lambda e: e["blocks"].append(copy.deepcopy(e["blocks"][0])),
            lambda e: e.update(operation_order="address-order"),
            lambda e: e["operations"].append(copy.deepcopy(e["operations"][-1])),
        ]
        for change in changes:
            data = snapshot(); change(data)
            with self.subTest(data=data), self.assertRaises(Unsupported): reconstruct(data)

    def test_reject_bad_offsets_widths_and_dynamic_addresses(self):
        for offset in (1, 64, (1 << 64)-4):
            e = Export()
            pointer = e.op("PTRSUB", [e.p, e.constant(offset, 8)], size=8)
            with self.assertRaises(Unsupported): reconstruct(e.finish(e.load(pointer)))
        e = Export(); pointer = e.op("PTRADD", [e.p, e.x, e.constant(4, 8)], size=8)
        with self.assertRaises(Unsupported): reconstruct(e.finish(e.load(pointer)))
        e = Export(); value = e.op("LOAD", [e.space, e.p], size=8)
        with self.assertRaises(Unsupported): reconstruct(e.finish(value))


if __name__ == "__main__":
    unittest.main()
