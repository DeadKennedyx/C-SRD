"""Observer regressions: residue classes, cyclic effects, malformed exports, controls."""
import copy
import ctypes
import json
from pathlib import Path
import shutil
import random
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"tools"))
from fit_region_values import fit_rows, score_models
from pcode_regions import reconstruct, RegionGraph, Unsupported
from region_observation_cases import driver, vectors, oracle, effects, parse_output, input_text


class AffineCongruence(unittest.TestCase):
    def test_nonunique_maps_and_heldout_values(self):
        # Values occupy cosets; original multipliers need not be identifiable.
        for shift in (0, 1, 2, 8, 20, 30):
            labels = [(i*(1 << shift)+7) % 2**32 for i in (0, 1, 3, 5, 11)]
            rows = [{"v": (0xf1234567*t+0x76543210) % 2**32} for t in labels]
            models, meta = fit_rows(rows, labels)
            self.assertEqual(len(models), 1)
            self.assertEqual(meta["parameter_solutions"], 1 << shift)
            model = models[0]
            for i in (9, 13, 0x7fffffff, 0xffffffff):
                t = (i*(1 << shift)+7) % 2**32
                value = (0xf1234567*t+0x76543210) % 2**32
                self.assertEqual(((value-model["b"])*model["inverse"]) % 2**32, t)

    def test_missing_locations_bad_labels_even_maps_and_constant_targets(self):
        labels = [3, 7, 11, 27, 43]
        models, _ = fit_rows([{"v":2*t} for t in labels], labels)
        self.assertFalse(models)  # non-invertible map
        rows = [{"v":3*t+7} for t in labels]; rows[-1]["v"] += 1
        self.assertFalse(fit_rows(rows, labels)[0])
        rows[-1] = {}
        self.assertEqual(fit_rows(rows, labels)[1]["locations_searched"], 0)
        self.assertEqual(fit_rows([{"v":7}]*3, [5]*3)[1]["status"], "insufficient-variation")
        self.assertIsNone(fit_rows([{"v":7}]*3, [5]*3)[1]["parameter_solutions"])

    def test_coset_overfitting_fails_heldout(self):
        labels = [0, 4, 8, 12]
        a = (1 << 30)+3
        models, _ = fit_rows([{"0:0:reg:x0":(a*t+1) % 2**32} for t in labels], labels)
        trace = {"samples":[{"offset":0,"visit":0,"values":{"reg:x0":(a+1) % 2**32}}]}
        scored = score_models(models, [trace], [1])
        self.assertEqual(scored["false_models"], 1)
        self.assertEqual(scored["validated_models"], 0)


class RegionReconstruction(unittest.TestCase):
    def setUp(self):
        self.export = json.loads((ROOT/"tests/fixtures/pcode_region_loop.json").read_text())

    def test_rejects_unknown_effects_and_invalid_cfg(self):
        variants = []
        d = copy.deepcopy(self.export); next(o for o in d["operations"] if o["opcode"]=="CALL")["callee"]="unknown"; variants.append(d)
        d = copy.deepcopy(self.export); d["operations"][0]["opcode"]="INDIRECT"; variants.append(d)
        d = copy.deepcopy(self.export); d["blocks"][0]["outgoing"][0]["reverse_index"]=99; variants.append(d)
        d = copy.deepcopy(self.export); next(o for o in d["operations"] if o["opcode"]=="MULTIEQUAL")["inputs"].pop(); variants.append(d)
        d = copy.deepcopy(self.export); d["address_space"]["id"]+=1; variants.append(d)
        d = copy.deepcopy(self.export); next(o for o in d["operations"] if o["opcode"]=="STORE")["inputs"][2]=2; variants.append(d)
        for d in variants:
            with self.assertRaises(Unsupported): reconstruct(d)

    def test_real_binary_loop_and_observable_mutations(self):
        compiler = shutil.which("cc")
        if not compiler: self.skipTest("C compiler unavailable")
        cases = vectors("region_pipeline", 96)
        expected = [effects(oracle("declarations", "region_pipeline", v)) for v in cases]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            harness = directory/"driver.c"; harness.write_text(driver("region_pipeline"))
            for mutation in (None, "return", "store", "call-argument", "drop-call", "branch"):
                source = directory/"recovered.c"; source.write_text(reconstruct(self.export, mutation=mutation))
                binary = directory/"run"
                r = subprocess.run([compiler,"-std=c11","-Wall","-Wextra","-Werror","-O2",str(source),str(harness),"-o",str(binary)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)
                r = subprocess.run([str(binary)],input="".join(input_text(v) for v in cases),capture_output=True,text=True,timeout=20)
                if mutation == "branch" and r.returncode in (70, 71): continue  # event/block budget detects the altered path
                self.assertEqual(r.returncode, 0, r.stderr)
                actual = [parse_output(line) for line in r.stdout.splitlines()]
                self.assertEqual(len(actual),len(expected))
                if mutation is None: self.assertEqual(actual,expected)
                else: self.assertNotEqual(actual,expected,mutation)

    def test_simultaneous_self_loop_phi(self):
        # Swapping two phi values must read the old edge state for BOTH values.
        # Sequential updates would collapse them to the same value.
        d = {"schema_version":5,"memory_model":"ordered-u32-regions-v1","status":"decompiled",
             "operation_order":"basic-block-live-order","function":"swap_loop","arity":3,
             "parameters":[{"kind":k,"read_only":False} for k in ("uint32-buffer","uint32","uint32")],
             "address_space":{"id":1,"pointer_bytes":8,"addressable_unit_bytes":1},"entry_block":0,
             "nodes":[{"size":4,"input":True,"parameter":1},{"size":4,"input":True,"parameter":2},
                      {"size":4,"constant":"3"},{"size":4,"constant":"1"},{"size":4,"constant":"0"},
                      {"size":8,"constant":"0"}]+[{"size":4} for _ in range(4)]+[{"size":1}],
             "operations":[],"blocks":[]}
        def op(code,ins,out=None):
            item={"opcode":code,"inputs":ins,"block":1}
            if out is not None:item["output"]=out
            d["operations"].append(item)
        op("MULTIEQUAL",[0,7],6);op("MULTIEQUAL",[1,6],7);op("MULTIEQUAL",[2,9],8)
        op("INT_SUB",[8,3],9);op("INT_LESS",[4,9],10);op("CBRANCH",[5,10])
        d["operations"].append({"opcode":"RETURN","inputs":[5,6],"block":2})
        d["blocks"]=[{"id":0,"operations":[],"incoming":[],"outgoing":[{"block":1,"reverse_index":0}]},
                     {"id":1,"operations":list(range(6)),"incoming":[{"block":0,"reverse_index":0},{"block":1,"reverse_index":1}],
                      "outgoing":[{"block":2,"reverse_index":0},{"block":1,"reverse_index":1}]},
                     {"id":2,"operations":[6],"incoming":[{"block":1,"reverse_index":0}],"outgoing":[]}]
        compiler=shutil.which("cc")
        if not compiler:self.skipTest("C compiler unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/"swap.c";binary=Path(temporary)/"swap"
            source.write_text(reconstruct(d)+"\nint main(void){uint32_t p[3]={0};return swap_loop(p,123,456)!=123;}\n")
            r=subprocess.run([compiler,"-std=c11","-Wall","-Wextra","-Werror","-O2",str(source),"-o",str(binary)],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertEqual(subprocess.run([str(binary)],timeout=5).returncode,0)

    def test_rare_return_path_is_in_grading_inputs(self):
        cases=vectors("region_outputs",32)
        returns=[oracle("assignments","region_outputs",v)["return_value"] for v in cases]
        self.assertIn(0,returns);self.assertIn(1,returns)

    def test_wide_signed_shift_against_integer_oracle(self):
        compiler=shutil.which("cc")
        if not compiler:self.skipTest("C compiler unavailable")
        sources=[];probes=[]
        for bits in (8,16,32,64):
            for count in (0,1,bits-1,bits,bits+1):
                name=f"probe_{bits}_{count}"
                d={"schema_version":5,"memory_model":"ordered-u32-regions-v1","status":"decompiled",
                   "operation_order":"basic-block-live-order","function":name,"arity":3,
                   "parameters":[{"kind":k,"read_only":False} for k in ("uint32-buffer","uint32","uint32")],
                   "address_space":{"id":1,"pointer_bytes":8,"addressable_unit_bytes":1},"entry_block":0,
                   "nodes":[{"size":4,"input":True,"parameter":1},{"size":4,"input":True,"parameter":2},
                            {"size":8,"input":True,"parameter":0},{"size":4,"constant":"1"},
                            {"size":8,"constant":"0"},{"size":8},{"size":bits//8},{"size":8,"constant":"0"},
                            {"size":1,"constant":str(count)},{"size":bits//8},{"size":8},{"size":4},{"size":4},
                            {"size":8,"constant":"4"},{"size":8}],"operations":[]}
                def op(code,ins,out=None):
                    item={"opcode":code,"inputs":ins,"block":0}
                    if out is not None:item["output"]=out
                    d["operations"].append(item)
                op("PIECE",[0,1],5);op("SUBPIECE",[5,7],6);op("INT_SRIGHT",[6,8],9);op("INT_SEXT",[9],10)
                op("SUBPIECE",[10,7],11);op("SUBPIECE",[10,13],12);op("PTRSUB",[2,13],14)
                op("STORE",[3,2,11]);op("STORE",[3,14,12]);op("RETURN",[4,11])
                d["blocks"]=[{"id":0,"operations":list(range(len(d["operations"]))),"incoming":[],"outgoing":[]}]
                sources.append(reconstruct(d));probes.append((name,bits,count))
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/"probes.c";library=Path(temporary)/"probes.so"
            source.write_text("\n".join(sources))
            r=subprocess.run([compiler,"-std=c11","-Wall","-Wextra","-Werror","-O2","-fPIC","-shared",str(source),"-o",str(library)],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            loaded=ctypes.CDLL(str(library));rng=random.Random(20261110)
            numbers=[0,1,2**64-1,2**63,2**63-1]+[rng.getrandbits(64) for _ in range(128)]
            for name,bits,count in probes:
                fn=getattr(loaded,name);fn.argtypes=[ctypes.POINTER(ctypes.c_uint32),ctypes.c_uint32,ctypes.c_uint32];fn.restype=ctypes.c_uint32
                for number in numbers:
                    value=number % (1 << bits)
                    signed=value-(1 << bits) if value & (1 << (bits-1)) else value
                    expected=(signed >> count) % 2**64
                    memory=(ctypes.c_uint32*3)(0,0,0x12345678)
                    result=fn(memory,number >> 32,number & 0xffffffff)
                    self.assertEqual(memory[0]+(memory[1] << 32),expected)
                    self.assertEqual(result,expected & 0xffffffff)
                    self.assertEqual(memory[2],0x12345678)


if __name__ == "__main__": unittest.main()
