"""Ordered opaque call contracts, real C reparsing and effect mutation controls."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOL = str(Path(sys.argv.pop(1)).resolve())
ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT/"tests/fixtures/calls.json"
PREAMBLE = """#include <stdint.h>
uint32_t effect_value(uint32_t); void effect_note(uint32_t);
uint32_t effect_mix(uint32_t*,uint32_t*,uint32_t);
void effect_bytes(unsigned char*,uint32_t);
"""


class Calls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.original = self.root/"original.c"; self.candidate = self.root/"candidate.c"
        self.report = self.root/"report.json"

    def tearDown(self): self.temp.cleanup()

    def run_tool(self, *args, code=0):
        result = subprocess.run([TOOL, *map(str, args)], capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, code, result.stderr)
        return result

    def transform(self, text, *args, contract=CONTRACTS):
        self.original.write_text(PREAMBLE+text+"\n")
        extra = ["--call-contracts", contract] if contract else []
        self.run_tool("transform", self.original, "-o", self.candidate, "--report", self.report, *extra, *args)
        return json.loads(self.report.read_text())["functions"][0]

    def compare(self, a, b, status="counterexample"):
        self.original.write_text(PREAMBLE+a+"\n"); self.candidate.write_text(PREAMBLE+b+"\n")
        self.run_tool("verify", self.original, self.candidate, "--report", self.report,
                      "--call-contracts", CONTRACTS, code=0 if status == "proved-under-model" else 3)
        result = json.loads(self.report.read_text())["functions"][0]
        self.assertEqual(result["verification"], status, result)
        return result

    def test_fixture_and_scalar_only_calls(self):
        for strategy in ("identity", "affine"):
            self.run_tool("transform", ROOT/"tests/fixtures/calls.c", "-o", self.candidate, "--report", self.report,
                          "--call-contracts", CONTRACTS, "--strategy", strategy, "--seed", 42)
            report = json.loads(self.report.read_text())
            self.assertEqual(len(report["functions"]), 7)
            self.assertEqual(len(report["call_contracts_sha256"]), 64)
            for f in report["functions"]:
                self.assertEqual(f["status"], "transformed", f)
                self.assertEqual(f["verification"], "proved-under-model", f)
                self.assertEqual(f["semantic_model"], "ordered-calls-byte-c11-v1")
                self.assertTrue(f["ordered_calls"])
        f = self.transform("uint32_t f(uint32_t x){uint32_t y=3u*x+11u;uint32_t z=effect_value(y);return 5u*z+y;}")
        self.assertEqual(f["verification"], "proved-under-model", f)
        self.assertEqual(f["operations_without_decoding"], 4)

    def test_event_order_arguments_and_unused_results(self):
        prefix = "uint32_t f(uint32_t x){"
        for a, b in (
            ("effect_note(x);effect_note(x+1u);", "effect_note(x+1u);effect_note(x);"),
            ("effect_note(x);", "effect_note(x+1u);"),
            ("effect_value(x);", ""),
            ("effect_value(x);", "effect_note(x);"),
            ("effect_value(x);", "effect_value(x);effect_value(x);"),
        ):
            with self.subTest(a=a,b=b): self.compare(prefix+a+"return 0u;}", prefix+b+"return 0u;}")
        self.compare(prefix+"uint32_t y=effect_value(x);return y+1u;}",
                     prefix+"uint32_t y=effect_value(x);return x+1u;}")

    def test_pre_call_memory_is_observable(self):
        self.compare("uint32_t f(uint32_t*p,uint32_t x){p[0]=x;effect_note(x);p[0]=0u;return 0u;}",
                     "uint32_t f(uint32_t*p,uint32_t x){effect_note(x);p[0]=0u;return 0u;}")

    def test_call_havoc_prevents_stale_loads(self):
        self.compare("uint32_t f(uint32_t*p,uint32_t*q,uint32_t x){uint32_t a=p[0];effect_mix(p,q,x);return p[0]+a;}",
                     "uint32_t f(uint32_t*p,uint32_t*q,uint32_t x){uint32_t a=p[0];effect_mix(p,q,x);return a+a;}")

    def test_pointer_arguments_preserve_alias_and_capture(self):
        a = "uint32_t f(uint32_t*p,uint32_t*q,uint32_t x){effect_mix(p,q,x);return 0u;}"
        b = "uint32_t f(uint32_t*p,uint32_t*q,uint32_t x){effect_mix(q,p,x);return 0u;}"
        self.compare(a,b)
        f = self.transform("uint32_t f(uint32_t*p,uint32_t*q,uint32_t x){uint32_t*r=p+(x&3u);x=x+1u;return effect_mix(r,q,x);}")
        self.assertEqual(f["verification"], "proved-under-model", f)
        self.assertEqual(f["parameters"][0]["minimum_elements"], 5)

    def test_equivalent_call_boundaries_and_renames(self):
        self.compare("uint32_t f(uint32_t x){uint32_t y=effect_value(3u*(x+1u));effect_note(y+1u);return y+1u;}",
                     "uint32_t f(uint32_t z){uint32_t a=effect_value(z*3u+3u);uint32_t b=a+1u;effect_note(b);return b;}",
                     "proved-under-model")

    def test_reject_unsupported_call_shapes_without_partial_edits(self):
        for body in (
            "return effect_value(x)+1u;", "return effect_value(effect_value(x));",
            "if(x){effect_note(x);}return x;", "for(uint32_t i=0;i<2u;++i){effect_note(x);}return x;",
            "return f(p,q,x);", "uint32_t(*fp)(uint32_t)=effect_value;return fp(x);",
            "return effect_mix(p+x,q,x);", "p[0]=effect_value(x);return x;",
        ):
            with self.subTest(body=body):
                f = self.transform("uint32_t f(uint32_t*p,uint32_t*q,uint32_t x){"+body+"}")
                self.assertEqual(f["status"], "unchanged", f)
                self.assertEqual(self.original.read_bytes(), self.candidate.read_bytes())
        f = self.transform("uint32_t f(uint32_t x){return effect_value(x);}", contract=None)
        self.assertEqual(f["status"], "unchanged")
        self.assertIn("explicit --call-contracts", f["reason"])

    def test_contract_types_and_malformed_options(self):
        text = "uint32_t f(uint32_t x){return effect_value(x);}"
        contract = json.loads(CONTRACTS.read_text()); contract["functions"][0]["returns"] = "void"
        path = self.root/"contracts.json"; path.write_text(json.dumps(contract))
        self.assertEqual(self.transform(text, contract=path)["status"], "unchanged")
        for bad in ({}, {"model":"pure", "functions":[]}, {"model":"opaque-sequenced-v1", "functions":[{"name":"g","returns":"uint32","parameters":[{"kind":"uint32","pure":True}]}]}):
            path.write_text(json.dumps(bad))
            self.run_tool("analyze", self.original, "--call-contracts", path, code=2)
        self.run_tool("transform", self.original, "-o", path, "--call-contracts", path, code=2)

    def test_zero_argument_calls_and_zero_footprint_const_pointer(self):
        path=self.root/"contracts.json"
        path.write_text(json.dumps({"model":"opaque-sequenced-v1","functions":[
            {"name":"f0","returns":"uint32","parameters":[]},
            {"name":"n0","returns":"void","parameters":[]},
            {"name":"peek","returns":"uint32","parameters":[{"kind":"uint32-buffer","read_only":True,"minimum_elements":0}]}
        ]}))
        for text in (
            "uint32_t f0(void);void n0(void);uint32_t f(void){uint32_t v=f0();n0();return 3u*v+7u;}",
            "uint32_t peek(const uint32_t*);uint32_t f(const uint32_t*p){return peek(p);}",
        ):
            f=self.transform(text,contract=path)
            self.assertEqual(f["verification"],"proved-under-model",f)
            if f["parameters"]:self.assertEqual(f["parameters"][0]["minimum_elements"],0)


if __name__ == "__main__": unittest.main()
