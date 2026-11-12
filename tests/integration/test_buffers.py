"""Actual-C memory validation, alias controls and conservative coverage checks."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOL = str(Path(sys.argv.pop(1)).resolve())
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from audit_protection import AuditError, require_one_function
from evaluate import analyze as evaluation_analysis


class Buffers(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.original = self.root / "original.c"
        self.candidate = self.root / "candidate.c"
        self.report = self.root / "report.json"

    def tearDown(self):
        self.temp.cleanup()

    def call(self, *args, code=0):
        run = subprocess.run([TOOL, *map(str, args)], capture_output=True, text=True, timeout=40)
        self.assertEqual(run.returncode, code, run.stderr)
        return run

    def transform(self, text, *args):
        self.original.write_text("#include <stdint.h>\n" + text + "\n")
        self.call("transform", self.original, "-o", self.candidate, "--report", self.report, *args)
        return json.loads(self.report.read_text())["functions"][0]

    def compare(self, original, candidate, status="counterexample"):
        self.original.write_text("#include <stdint.h>\n" + original + "\n")
        self.candidate.write_text("#include <stdint.h>\n" + candidate + "\n")
        self.call("verify", self.original, self.candidate, "--report", self.report,
                  code=0 if status == "proved-under-model" else 3)
        decision = json.loads(self.report.read_text())["functions"][0]
        self.assertEqual(decision["verification"], status, decision)
        return decision["proof"]

    def test_generated_artifact_keeps_encoded_regions_and_bounds(self):
        source = "uint32_t f(uint32_t *p,uint32_t x){uint32_t s=p[0]+x;uint32_t t=3u*s+11u;p[1]=t;return t-7u;}"
        for seed in (0, 42, 18446744073709551615):
            d = self.transform(source, "--seed", seed)
            self.assertEqual(d["status"], "transformed")
            self.assertEqual(d["semantic_model"], "buffers-u32-c11-v1")
            self.assertEqual(d["verification"], "proved-under-model")
            self.assertEqual(d["operations_without_decoding"], 4)
            self.assertEqual(d["encodings"], 2)  # scalar argument and one load
            self.assertEqual(d["decodings"], 2)  # store and return, not each arithmetic operation
            self.assertEqual(d["parameters"][0]["minimum_elements"], 2)
            text = self.candidate.read_bytes()
            report = json.loads(self.report.read_text())
            self.assertEqual(report["candidate_sha256"], hashlib.sha256(text).hexdigest())
            self.transform(source, "--seed", seed)
            self.assertEqual(text, self.candidate.read_bytes())
        d = self.transform(source, "--strategy", "identity")
        self.assertEqual(d["verification"], "proved-under-model")
        self.assertEqual(d["encodings"] + d["decodings"], 0)

    def test_alias_sensitive_store_and_load_order(self):
        self.compare("uint32_t f(uint32_t*p,uint32_t*q,uint32_t x){p[1]=x;return q[0];}",
                     "uint32_t f(uint32_t*p,uint32_t*q,uint32_t x){uint32_t v=q[0];p[1]=x;return v;}")
        self.compare("uint32_t f(uint32_t*p,uint32_t*q,uint32_t x){p[0]=x;q[0]=x+1u;return 0u;}",
                     "uint32_t f(uint32_t*p,uint32_t*q,uint32_t x){q[0]=x+1u;p[0]=x;return 0u;}")

    def test_equivalent_different_source_and_renamed_parameters(self):
        self.compare("uint32_t f(uint32_t*p,uint32_t x){p[0]=3u*(x+1u);return *p;}",
                     "uint32_t f(uint32_t*q,uint32_t y){q[0]=y*3u+3u;return q[0];}",
                     "proved-under-model")

    def test_memory_only_counterexample_and_compiled_replay(self):
        proof = self.compare("uint32_t f(uint32_t*p,uint32_t x){*p=x+1u;return 7u;}",
                             "uint32_t f(uint32_t*p,uint32_t x){*p=x+2u;return 7u;}")
        self.assertEqual(proof["original_output"], proof["candidate_output"])
        cell, = proof["memory_cells"]
        self.assertNotEqual(cell["original"], cell["candidate"])
        compiler = shutil.which("clang") or shutil.which("cc")
        for label, path in (("original", self.original), ("candidate", self.candidate)):
            subprocess.run([compiler, "-std=c11", f"-Df={label}", "-c", str(path), "-o",
                            str(self.root / f"{label}.o")], check=True, capture_output=True)
        driver = self.root / "replay.c"
        driver.write_text(f'''#include <stdint.h>
uint32_t original(uint32_t*,uint32_t); uint32_t candidate(uint32_t*,uint32_t);
int main(void) {{ uint32_t a={cell['initial']}u,b=a;
return original(&a,{proof['inputs'][0]}u)!=7u || candidate(&b,{proof['inputs'][0]}u)!=7u ||
a!={cell['original']}u || b!={cell['candidate']}u || a==b; }}
''')
        binary = self.root / "replay"
        subprocess.run([compiler, str(driver), str(self.root / "original.o"),
                        str(self.root / "candidate.o"), "-o", str(binary)], check=True, capture_output=True)
        subprocess.run([str(binary)], check=True)

    def test_untouched_cell_and_index_corruption(self):
        self.compare("uint32_t f(uint32_t*p,uint32_t x){uint32_t a=p[2];p[0]=x;return a;}",
                     "uint32_t f(uint32_t*p,uint32_t x){uint32_t a=p[2];p[0]=x;p[1]=x;return a;}")
        self.compare("uint32_t f(uint32_t*p){return p[0]+p[1];}",
                     "uint32_t f(uint32_t*p){return p[0]+p[0];}")

    def test_no_larger_footprint_or_signature_change(self):
        original = "uint32_t f(uint32_t*p,uint32_t x){p[0]=x;return x;}"
        for candidate in (
            "uint32_t f(uint32_t*p,uint32_t x){p[1]=x;return x;}",
            "uint32_t f(const uint32_t*p,uint32_t x){return x;}",
            "uint32_t f(uint32_t p,uint32_t x){return x;}",
        ):
            self.compare(original, candidate, "unsupported")

    def test_const_aliases_and_unused_null_capability(self):
        d = self.transform("uint32_t f(const uint32_t*p,uint32_t*q,uint32_t x){uint32_t b=*p;*q=x;return b+*p;}")
        self.assertEqual(d["verification"], "proved-under-model")
        self.assertTrue(d["parameters"][0]["read_only"])
        d = self.transform("uint32_t f(uint32_t*p,uint32_t x){(void)p;return x+1u;}")
        self.assertEqual(d["parameters"][0]["minimum_elements"], 0)
        self.assertEqual(d["verification"], "proved-under-model")

    def test_unsupported_constructs_leave_whole_function_unchanged(self):
        bodies = ["return p[x];", "p++;return *p;", "p[0]+=x;return x;",
                  "if(x){p[0]=x;}return x;", "for(uint32_t i=0;i<2u;++i){p[0]=x;}return x;",
                  "return p[256];", "return p[-1];", "return p[0]*x;",
                  "uint32_t a[2]={1u,2u};return a[0];",
                  "extern uint32_t g(uint32_t*);return g(p);"]
        for body in bodies:
            with self.subTest(body=body):
                d = self.transform(f"uint32_t f(uint32_t*p,uint32_t x){{{body}}}")
                self.assertEqual(d["status"], "unchanged", d)
                self.assertTrue(d["reason"])
                self.assertEqual(self.original.read_bytes(), self.candidate.read_bytes())

    def test_qualifiers_array_declarators_and_pointer_types_rejected(self):
        for parameter in ("volatile uint32_t*p", "uint32_t*restrict p", "uint32_t*const p",
                          "_Atomic(uint32_t)*p", "int*p", "uint32_t p[2]", "uint32_t**p"):
            with self.subTest(parameter=parameter):
                d = self.transform(f"uint32_t f({parameter}){{(void)p;return 0u;}}")
                self.assertEqual(d["status"], "unchanged")

    def test_unsupported_strategies_are_explicit(self):
        source = "uint32_t f(uint32_t*p){return *p+1u;}"
        for option, value in (("--strategy", "planned"), ("--strategy", "xor"),
                              ("--strategy", "limbs4"), ("--control-flow", "split-scale"),
                              ("--algorithm", "popcount8-serial")):
            d = self.transform(source, option, value)
            self.assertEqual(d["status"], "unchanged")
            self.assertIn("regions support only affine/identity", d["reason"])

    def test_names_macros_and_line_preservation(self):
        d = self.transform("#define csrd_mem_0 collision\nuint32_t f(uint32_t*p,uint32_t csrd_mem_1){\nuint32_t csrd_mem_2=*p+csrd_mem_1;\np[0]=csrd_mem_2;\nreturn *p;\n}\nint line=__LINE__;")
        self.assertEqual(d["verification"], "proved-under-model")
        self.assertEqual(self.original.read_text().count("\n"), self.candidate.read_text().count("\n"))
        self.assertNotIn("unsigned int csrd_mem_0", self.candidate.read_text())
        d = self.transform("#define LOAD(p) p[0]\nuint32_t f(uint32_t*p){return LOAD(p);}")
        self.assertEqual(d["status"], "unchanged")

    def test_scalar_observers_explicitly_reject_memory_interfaces(self):
        self.transform("uint32_t f(uint32_t*p,uint32_t x){p[0]=x;return x;}")
        self.call("analyze", self.original, "--report", self.report)
        report = json.loads(self.report.read_text())
        with self.assertRaisesRegex(AuditError, "buffer interfaces are unsupported"):
            require_one_function(report)
        self.assertEqual(require_one_function(report, allow_memory=True)["semantic_model"], "buffers-u32-c11-v1")
        for body in ("p[0]=x;return x;", "return p[x];"):
            self.original.write_text("#include <stdint.h>\nuint32_t kernel(uint32_t*p,uint32_t x){" + body + "}\n")
            with self.assertRaises(RuntimeError):
                evaluation_analysis(TOOL, self.original)

    def test_bytes_indexes_and_captured_pointer_offsets(self):
        cases = (
            "uint32_t f(unsigned char*p,uint32_t x){uint32_t i=x&7u;uint32_t s=p[i]+x;p[i]=3u*s+11u;return s+p[i];}",
            "uint32_t f(uint32_t*p,uint32_t x){uint32_t*q=p+(x&7u);x=x+1u;q[0]=x;return p[0]+*q;}",
            "uint32_t f(unsigned char*p,uint32_t x){unsigned char*q=1u+p;unsigned char*r=q+(x&3u);*r=x;return p[0]+r[0];}",
            "uint32_t f(const char*s,uint32_t x){return (uint32_t)s[x&3u]+x;}",
            "uint32_t f(unsigned char*p){return p[0]+3*p[1]+(p[2]<<8);}",
            "uint32_t f(signed char*p,uint32_t x){p[0]=(signed char)x;return (uint32_t)*p;}",
            "uint32_t f(uint32_t*p,uint32_t x){return x ? p[0] : p[1];}",
        )
        for source in cases:
            for strategy in ("identity", "affine"):
                with self.subTest(source=source, strategy=strategy):
                    decision = self.transform(source, "--strategy", strategy, "--seed", 42)
                    self.assertEqual(decision["status"], "transformed", decision)
                    self.assertEqual(decision["semantic_model"], "buffers-byte-c11-v2")
                    self.assertEqual(decision["verification"], "proved-under-model", decision)

    def test_byte_alias_and_dynamic_index_corruption(self):
        proof = self.compare(
            "uint32_t f(unsigned char*p,uint32_t*q,uint32_t x){p[x&3u]=x;return q[0];}",
            "uint32_t f(unsigned char*p,uint32_t*q,uint32_t x){uint32_t r=q[0];p[x&3u]=x;return r;}")
        self.assertEqual(proof["address_unit"], "byte")
        self.assertTrue(proof["pointer_byte_bases"])
        self.assertTrue(all(0 <= cell["initial"] < 256 for cell in proof["memory_cells"]))
        self.compare("uint32_t f(unsigned char*p,uint32_t x){return p[x&7u];}",
                     "uint32_t f(unsigned char*p,uint32_t x){return p[x&3u];}")
        self.compare("uint32_t f(char*p,uint32_t x){return (uint32_t)p[0]+x;}",
                     "uint32_t f(char*p,uint32_t x){return (uint32_t)(unsigned char)p[0]+x;}",
                     "counterexample" if self.transform("uint32_t f(char*p){return (uint32_t)p[0];}")["parameters"][0]["element_signed"] else "proved-under-model")

    def test_byte_narrowing_and_whole_memory_equivalence(self):
        self.compare("uint32_t f(unsigned char*p,uint32_t x){p[0]=x;return x;}",
                     "uint32_t f(unsigned char*q,uint32_t y){q[0]=y&255u;return y;}", "proved-under-model")
        self.compare("uint32_t f(unsigned char*p,uint32_t x){p[0]=x;return 0u;}",
                     "uint32_t f(unsigned char*p,uint32_t x){p[0]=x+256u;return 0u;}", "proved-under-model")
        self.compare("uint32_t f(unsigned char*p,uint32_t x){p[0]=x;return 0u;}",
                     "uint32_t f(unsigned char*p,uint32_t x){p[0]=x+1u;return 0u;}")

    def test_unsafe_byte_promotions_and_pointer_casts_rejected(self):
        sources = (
            "uint32_t f(unsigned char*p){return p[0]<<31;}",
            "uint32_t f(unsigned char*p){return p[0]*2147483647;}",
            "uint32_t f(signed char*p){return p[0]+1;}",
            "uint32_t f(unsigned char*p){uint32_t*q=(uint32_t*)p;return *q;}",
            "uint32_t f(uint32_t*p){unsigned char*q=(unsigned char*)p;return *q;}",
            "uint32_t f(unsigned char*p,uint32_t x){unsigned char*q=p+x;return *q;}",
            "uint32_t f(unsigned char*p,uint32_t x){return p[(x&255u)+1u];}",
            "uint32_t f(unsigned char*p,uint32_t x){return p[x++&3u];}",
        )
        for source in sources:
            with self.subTest(source=source):
                decision = self.transform(source)
                self.assertEqual(decision["status"], "unchanged", decision)
                self.assertEqual(self.original.read_bytes(), self.candidate.read_bytes())


if __name__ == "__main__":
    unittest.main()
