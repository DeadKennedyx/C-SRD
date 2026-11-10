"""Pinned NEON/constant tests: independent SMT, integer oracles and hardware."""
import copy
import json
from pathlib import Path
import platform
import random
import shutil
import subprocess
import sys
import unittest

from test_pcode_wide import directory, input_expression

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from pcode_values import Builder, Value, literal
from pcode_vector import readonly_value, userop_name
from pcode_reconstruct import reconstruct, Unsupported

TOOL = str(Path(sys.argv.pop(1)).resolve())
PARAMS = ",".join(f"unsigned int p{i}" for i in range(9))
META = {"schema_version":3,"language":"AARCH64:LE:64:v8A","ghidra_version":"12.2",
        "memory_model":"immutable-mapped-constants-v1"}


def cases():
    result = []
    for bits in (64, 128):
        result += [("NEON_ext", bits, 1, k) for k in range(bits//8)]
        result += [("NEON_rev64", bits, k, 0) for k in (1, 2, 4)]
        for lane in (1, 2, 4, 8):
            for count in (-128, -65, -64, -33, -32, -17, -16, -8, -1, 0, 1, 7, 8, 16, 31, 32, 63, 64, 127):
                result.append(("NEON_ushl", bits, lane, count))
    return result


def counts_value(bits, lane, count):
    # Alternating counts, and irrelevant nonzero upper bytes of each lane.
    return sum((((count+i) & 255) | ((0x5a5a5a5a5a5a5a00) & ((1 << (8*lane))-1))) << (8*lane*i)
               for i in range(bits//(8*lane)))


def generate(case):
    name, bits, lane, count = case
    builder = Builder({"evaluated_operations":0})
    def value(base):
        return Value(bits,"",None,tuple(Value(32,f"p{base+i}") for i in range(bits//32)))
    a = value(0)
    if name == "NEON_ext": args = [a, value(4), literal(8,count), literal(8,lane)]
    elif name == "NEON_rev64": args = [a,literal(8,lane)]
    else: args = [a,literal(bits,counts_value(bits,lane,count)),literal(8,lane)]
    result = builder.operation(name,bits,args)
    unused = "\n".join([*(f"(void)p{i};" for i in range(9)),*(f"(void)v{i};" for i in range(builder.serial))])
    prefix = f"unsigned int f({PARAMS}){{\n"+"\n".join(builder.lines)+"\n"+unused
    return [prefix+f"\nreturn {v.atom};\n}}\n" for v in result.parts]


def smt(case):
    name,bits,lane,count=case
    a,b=input_expression(bits,0),input_expression(bits,4)
    if name == "NEON_ext": return f"((_ extract {8*count+bits-1} {8*count}) (concat {b} {a}))"
    expressions=[]
    width=8*lane
    for i in range(bits//width):
        if name == "NEON_rev64":
            j=i//(64//width)*(64//width)+(64//width)-1-i%(64//width)
            expressions.append(f"((_ extract {j*width+width-1} {j*width}) {a})")
        else:
            low=(counts_value(bits,lane,count) >> (i*width)) & 255
            signed=low-256 if low & 128 else low
            operand=f"((_ extract {i*width+width-1} {i*width}) {a})"
            expressions.append(f"({'bvlshr' if signed < 0 else 'bvshl'} {operand} (_ bv{min(abs(signed),width)} {width}))")
    result=expressions[-1]
    for expression in reversed(expressions[:-1]): result=f"(concat {result} {expression})"
    return result


def oracle(case,inputs):
    name,bits,lane,count=case
    a=sum(inputs[i] << (32*i) for i in range(bits//32))
    b=sum(inputs[4+i] << (32*i) for i in range(bits//32))
    if name == "NEON_ext": return ((a | (b << bits)) >> (8*count)) & ((1 << bits)-1)
    if name == "NEON_rev64":
        data=a.to_bytes(bits//8,"little")
        result=b"".join(b"".join(data[base+j:base+j+lane] for j in range(8-lane,-1,-lane)) for base in range(0,len(data),8))
        return int.from_bytes(result,"little")
    value=0; width=8*lane; counts=counts_value(bits,lane,count).to_bytes(bits//8,"little")
    for i in range(bits//width):
        signed=int.from_bytes(counts[i*lane:i*lane+1],"little",signed=True)
        digit=(a >> (i*width)) & ((1 << width)-1)
        result=(digit >> min(-signed,width)) if signed < 0 else (digit << min(signed,width))
        value |= (result & ((1 << width)-1)) << (i*width)
    return value


def hardware(case,part,index):
    name,bits,lane,count=case
    q="q" if bits == 128 else ""
    vu=f"uint8x{bits//8}_t"
    source=f"unsigned int h{index}({PARAMS}){{\nuint32_t data[8]={{p0,p1,p2,p3,p4,p5,p6,p7}};(void)p8;\n"
    source+=f"{vu} a=vld1{q}_u8((const uint8_t*)data);\n"
    if name == "NEON_ext":
        source+=f"{vu} b=vld1{q}_u8((const uint8_t*)(data+4));\n{vu} r=vext{q}_u8(a,b,{count});\n"
    elif name == "NEON_rev64":
        typed="a" if lane==1 else f"vreinterpret{q}_u{8*lane}_u8(a)"
        expr=f"vrev64{q}_u{8*lane}({typed})"
        if lane!=1:expr=f"vreinterpret{q}_u8_u{8*lane}({expr})"
        source+=f"{vu} r={expr};\n"
    else:
        raw=counts_value(bits,lane,count).to_bytes(bits//8,"little")
        source+="const uint8_t counts[]={"+",".join(str(v) for v in raw)+"};\n"
        source+=f"{vu} c=vld1{q}_u8(counts);\n"
        typed="a" if lane==1 else f"vreinterpret{q}_u{8*lane}_u8(a)"
        expr=f"vshl{q}_u{8*lane}({typed},vreinterpret{q}_s{8*lane}_u8(c))"
        if lane!=1:expr=f"vreinterpret{q}_u8_u{8*lane}({expr})"
        source+=f"{vu} r={expr};\n"
    source+=f"return vget{q}_lane_u32(vreinterpret{q}_u32_u8(r),{part});\n}}\n"
    return source


class Vector(unittest.TestCase):
    def test_actual_c_matches_vector_smt(self):
        with directory("vector-proofs") as root:
            rows=[]
            for i,case in enumerate(cases()):
                for part,source in enumerate(generate(case)):
                    folder=root/f"case-{i}-{part}";folder.mkdir()
                    (folder/"actual.c").write_text(source)
                    (folder/"reference.c").write_text(f"unsigned int f({PARAMS}){{return p8;}}\n")
                    p=subprocess.run([TOOL,"verify",folder/"reference.c",folder/"actual.c","--report",folder/"model.json"],capture_output=True)
                    self.assertEqual(p.returncode,3,p.stderr)
                    query=json.loads((folder/"model.json").read_text())["functions"][0]["proof"]["smtlib"]
                    expected=f"((_ extract {32*part+31} {32*part}) {smt(case)})"
                    declarations="".join(f"(declare-fun input_{j} () (_ BitVec 32))\n" for j in range(9) if f"(declare-fun input_{j} " not in query)
                    query=declarations+query.replace("(check-sat)",f"(assert (= input_8 {expected}))\n(check-sat)")
                    (folder/"query.smt2").write_text(query)
                    p=subprocess.run([shutil.which("z3"),"-T:10",folder/"query.smt2"],capture_output=True,text=True,timeout=15)
                    self.assertEqual(p.stdout.strip(),"unsat",(case,part,p.stdout,p.stderr))
                    rows.append({"case":case,"part":part,"status":"unsat"})
            (root/"summary.json").write_text(json.dumps(rows,indent=2)+"\n")
            print("vector actual-C universal obligations:",len(rows),flush=True)

    def test_compiled_oracle_and_arm_intrinsics(self):
        native=platform.machine().lower() in ("arm64","aarch64") and sys.byteorder=="little"
        rng=random.Random(733007)
        vectors=[[v]*9 for v in (0,1,255,65535,0x80000000,0xffffffff)]
        vectors += [[rng.getrandbits(32) for _ in range(9)] for _ in range(64)]
        sources=[];checks=[]
        for case in cases():
            for part,source in enumerate(generate(case)):
                i=len(checks);sources.append(source.replace("unsigned int f(",f"unsigned int f{i}(",1))
                if native:sources.append(hardware(case,part,i))
                checks.append([oracle(case,v) >> (32*part) & 0xffffffff for v in vectors])
        source="#include <stdio.h>\n"+("#include <arm_neon.h>\n" if native else "")+"\n".join(sources)
        source+="static const unsigned int inputs[][9]={"+",".join("{"+",".join(str(x)+"u" for x in v)+"}" for v in vectors)+"};\nint main(void){\n"
        for i,values in enumerate(checks):
            source+="{const unsigned int expected[]={"+",".join(str(v)+"u" for v in values)+"};\n"
            args=",".join(f"p[{j}]" for j in range(9))
            comparisons=f"f{i}({args})!=expected[i]"+(f"||h{i}({args})!=expected[i]" if native else "")
            source+=f"for(unsigned int i=0;i<{len(vectors)}u;++i){{const unsigned int *p=inputs[i];if({comparisons}){{puts(\"case{i}\");return 1;}}}}}}\n"
        source+="return 0;}\n"
        compilers=[shutil.which("gcc-16") or shutil.which("gcc"),shutil.which("clang-18") or shutil.which("clang")]
        with directory("vector-compiled") as root:
            (root/"check.c").write_text(source)
            configs=[(c,[o]) for c in compilers for o in ("-O0","-O2")]+[(compilers[1],["-O1","-fsanitize=address,undefined","-fno-sanitize-recover=all"])]
            for i,(compiler,flags) in enumerate(configs):
                p=subprocess.run([compiler,"-std=c11","-pedantic-errors","-Wall","-Wextra","-Werror",*flags,root/"check.c","-o",root/f"check-{i}"],capture_output=True)
                self.assertEqual(p.returncode,0,p.stderr[:4000])
                p=subprocess.run([root/f"check-{i}"],capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            (root/"summary.json").write_text(json.dumps({"outputs":len(checks),"vectors":len(vectors),"builds":5,"arm_intrinsics":native})+"\n")
            print("vector compiled checks:",len(checks),"outputs x",len(vectors),"vectors x 5 builds; ARM intrinsics",native,flush=True)

    def test_rejects_unjustified_memory_and_userop_facts(self):
        node={"size":4,"input":True,"storage":"1000","readonly":{"bytes_hex":"2a000000","byte_order":"little","address":"1000",
              "block_start":"1000","block_end":"1003","read":True,"write":False,"execute":False,"initialized":True,"relocations":False}}
        self.assertEqual(readonly_value(META,node).known,42)
        executable=copy.deepcopy(node);executable["readonly"]["execute"]=True
        self.assertEqual(readonly_value(META,executable).known,42)
        for key,value in (("write",True),("execute","false"),("initialized",False),("relocations",True),("read",False),("byte_order","big"),("bytes_hex","2a00"),("block_end","1002"),("address","1001")):
            wrong=copy.deepcopy(node);wrong["readonly"][key]=value
            with self.assertRaises(Unsupported):readonly_value(META,wrong)
        for key,value in (("schema_version",2),("language","x86:LE:64:default"),("ghidra_version","12.1")):
            with self.assertRaises(Unsupported):readonly_value({**META,key:value},node)
        with self.assertRaises(Unsupported):userop_name({**META,"userops":{"7":"unknown"}},{"inputs":[0]},{0:literal(32,7)})
        builder=Builder({"evaluated_operations":0});a=Value(64,"",None,(Value(32,"x"),Value(32,"y")))
        with self.assertRaises(Unsupported):builder.operation("NEON_ushl",64,[a,a,literal(8,4)])
        with self.assertRaises(Unsupported):builder.operation("NEON_ext",64,[a,a,literal(8,8),literal(8,1)])
        with self.assertRaises(Unsupported):builder.operation("NEON_rev64",64,[a,literal(8,8)])
        # Correct and altered immutable bytes must not be graded as equivalent.
        graph={**META,"function":"f","arity":1,"entry_block":0,"userops":{},
               "nodes":[{"size":4,"parameter":0,"input":True},node,{"size":8,"constant":"0"}],
               "operations":[{"block":0,"opcode":"RETURN","inputs":[2,1]}],
               "blocks":[{"id":0,"operations":[0],"incoming":[],"outgoing":[]}]}
        with directory("vector-controls") as root:
            (root/"reference.c").write_text("unsigned int f(unsigned int x){(void)x;return 42u;}\n")
            for wrong in (False,True):
                changed=copy.deepcopy(graph)
                if wrong:changed["nodes"][1]["readonly"]["bytes_hex"]="2b000000"
                (root/"candidate.c").write_text(reconstruct(changed))
                p=subprocess.run([TOOL,"verify",root/"reference.c",root/"candidate.c"],capture_output=True)
                self.assertEqual(p.returncode,3 if wrong else 0,p.stderr)

    def test_wrong_vector_operation_controls(self):
        pairs=[(("NEON_ext",128,1,1),("NEON_ext",128,1,2)),
               (("NEON_rev64",128,1,0),("NEON_rev64",128,2,0)),
               (("NEON_ushl",128,4,1),("NEON_ushl",128,4,-1))]
        with directory("vector-wrong-operations") as root:
            for i,(correct,wrong) in enumerate(pairs):
                (root/"correct.c").write_text(generate(correct)[0])
                (root/"wrong.c").write_text(generate(wrong)[0])
                p=subprocess.run([TOOL,"verify",root/"correct.c",root/"wrong.c","--report",root/f"control-{i}.json"],capture_output=True)
                self.assertEqual(p.returncode,3,p.stderr)
                self.assertEqual(json.loads((root/f"control-{i}.json").read_text())["functions"][0]["verification"],"counterexample")


if __name__ == "__main__":unittest.main()
