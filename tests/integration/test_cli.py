"""Black-box checks: rejection, byte preservation, diagnostics and deterministic output."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOL = str(Path(sys.argv.pop(1)).resolve())


class CLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.src = self.root / "input.c"
        self.out = self.root / "output.c"
        self.report = self.root / "report.json"

    def tearDown(self):
        self.tmp.cleanup()

    def run_source(self, source, *args, expected=0):
        self.src.write_text(source)
        p = subprocess.run([TOOL, "transform", str(self.src), "-o", str(self.out),
                            "--report", str(self.report), *args], capture_output=True, text=True)
        self.assertEqual(p.returncode, expected, p.stderr)
        if expected == 0:
            return self.out.read_text(), json.loads(self.report.read_text()), p.stderr
        return p

    def test_supported_and_seed(self):
        source = "#include <stdint.h>\nuint32_t f(uint32_t x, uint32_t y) {uint32_t a=x+y; a=a*3u; return a+11u;}\n"
        a, report, _ = self.run_source(source, "--seed", "42")
        b, again, _ = self.run_source(source, "--seed", "42")
        self.assertEqual(a, b)
        self.assertEqual(report, again)
        self.assertNotEqual(a, source)
        self.assertEqual(a.count("\n"), source.count("\n"))
        decision = report["functions"][0]
        self.assertEqual(decision["operations_without_decoding"], 3)
        self.assertEqual(decision["boundary_conversions"], 3)
        self.assertEqual(decision["internal_conversions"], 0)
        self.assertEqual(decision["verification"], "proved-under-model")
        self.assertEqual((decision["a"] * decision["inverse"]) & 0xffffffff, 1)
        c, _, _ = self.run_source(source, "--seed", "43")
        self.assertNotEqual(a, c)

    def test_rejection_matrix(self):
        bodies = {
            "general multiplication": "return x*y;",
            "signed arithmetic": "return 2+3;",
            "wide arithmetic": "return x+4294967296ULL;",
            "uninitialized local": "uint32_t a; return a;",
            "self initialization": "uint32_t a=a; return a;",
            "pointer": "uint32_t *p=&x; return *p;",
            "volatile": "volatile uint32_t a=x; return a;",
            "atomic": "_Atomic uint32_t a=x; return a;",
            "static storage": "static uint32_t a=1u; return a;",
            "const local": "const uint32_t a=x; return a;",
            "increment": "x++; return x;",
            "nested assignment": "return (x=y)+x;",
            "compound assignment": "x+=y; return x;",
            "call": "return external(x);",
            "early return": "return x; return y;",
            "branch": "if(x) return y; return x;",
            "loop": "while(x) x=x-1u; return x;",
            "nested scope": "{uint32_t a=x;} return y;",
            "volatile global read": "return global+x;",
            "volatile global write": "global=x; return x;",
            "multiple declarations": "uint32_t a=x,b=y; return a+b;",
            "explicit cast": "return (uint32_t)x;",
            "unary negation": "return -x;",
            "overshift": "return x<<32u;",
            "dynamic shift": "return x<<y;",
            "sizeof": "return sizeof(x);",
            "vla": "uint32_t a[x]; return y;",
            "floating": "return x+1.5;",
            "empty statement": "; return x;",
            "function pointer": "uint32_t (*p)(uint32_t)=external; return p(x);",
            "local attribute": "uint32_t a __attribute__((aligned(32)))=x; return a;",
        }
        prefix = "#include <stdint.h>\nvolatile uint32_t global; uint32_t external(uint32_t);\n"
        for name, body in bodies.items():
            with self.subTest(name=name):
                source = prefix + "uint32_t f(uint32_t x,uint32_t y){" + body + "}\n"
                out, report, diag = self.run_source(source)
                self.assertEqual(out, source)
                self.assertEqual(report["functions"][0]["status"], "unchanged")
                self.assertTrue(report["functions"][0]["reason"])
                self.assertIn("input.c:", diag)

    def test_preprocessor_boundaries(self):
        sources = [
            "#define ID(x) x\nuint32_t f(uint32_t x){return ID(x)+1u;}\n",
            "#define EMPTY\nuint32_t f(uint32_t x){EMPTY return x+1u;}\n",
            "#define TYPE uint32_t\nTYPE f(uint32_t x){return x+1u;}\n",
            "#define VALUE 1u\nuint32_t f(uint32_t x){return x+VALUE;}\n",
            "uint32_t f(uint32_t x){\n#if 1\nreturn x+1u;\n#endif\n}\n",
            "uint32_t f(uint32_t x){\n#define FUTURE 7\nreturn x+1u;\n}\n",
            'uint32_t f(uint32_t x){_Pragma("GCC diagnostic push") return x+1u;}\n',
            "#define int long\nuint32_t f(uint32_t x){return x+1u;}\n#undef int\n",
            "#define BODY {return x+1u;}\nuint32_t f(uint32_t x) BODY\n",
        ]
        for tail in sources:
            with self.subTest(source=tail):
                source = "#include <stdint.h>\n" + tail
                out, report, _ = self.run_source(source)
                self.assertEqual(out, source)
                self.assertEqual(report["functions"][0]["status"], "unchanged")

    def test_function_contracts(self):
        signatures = ["int f(int x)", "uint32_t f(const uint32_t x)",
                      "uint32_t f(uint32_t **x)", "uint32_t f(uint32_t x,...)",
                      "uint32_t __attribute__((noinline)) f(uint32_t x)"]
        for signature in signatures:
            with self.subTest(signature=signature):
                source = "#include <stdint.h>\n" + signature + "{return 1u;}\n"
                out, _, _ = self.run_source(source)
                self.assertEqual(out, source)

    def test_nullary_literals_aliases_and_parenthesized_target(self):
        source = """#include <stdint.h>
typedef uint32_t word;
uint32_t zero(void) { return 0; }
uint32_t max(void) { return 4294967295u; }
word identity(word x) { return (x); }
word assign(word x) { (x) = x+1; return x; }
int main(void) { return zero()!=0u || max()!=4294967295u ||
    identity(2147483648u)!=2147483648u || assign(4294967295u)!=0u; }
"""
        _, report, _ = self.run_source(source)
        self.assertEqual([d["status"] for d in report["functions"]], ["transformed"] * 4 + ["unchanged"])
        compiler = shutil.which("clang") or shutil.which("cc")
        self.assertIsNotNone(compiler, "a C compiler is required for emitted-code validation")
        for path in [self.src, self.out]:
            binary = self.root / (path.stem + "-test")
            subprocess.run([compiler, "-std=c11", "-pedantic-errors", str(path), "-o", str(binary)], check=True, capture_output=True)
            subprocess.run([str(binary)], check=True, capture_output=True)

    def test_partial_translation_unit(self):
        source = "#include <stdint.h>\nuint32_t good(uint32_t x){return x+1u;}\nuint32_t bad(uint32_t x){return x*x;}\n"
        out, report, _ = self.run_source(source)
        self.assertEqual([d["status"] for d in report["functions"]], ["transformed", "unchanged"])
        self.assertEqual(out.splitlines()[-1], source.splitlines()[-1])

    def test_parse_error_preserves_output(self):
        self.out.write_text("sentinel")
        self.run_source("#include <stdint.h>\nuint32_t f( {\n", expected=1)
        self.assertEqual(self.out.read_text(), "sentinel")
        self.assertFalse(self.report.exists())

    def test_cr_line_endings_preserve_later_line_macro(self):
        source = "#include <stdint.h>\ruint32_t f(uint32_t x)\r{\ruint32_t y=x+1u;\rreturn y*3u;\r}\rint main(void){return __LINE__!=7 || f(1u)!=6u;}\r"
        self.run_source(source)
        compiler = shutil.which("clang") or shutil.which("cc")
        for path in [self.src, self.out]:
            binary = self.root / (path.stem + "-lines")
            subprocess.run([compiler, "-std=c11", str(path), "-o", str(binary)], check=True, capture_output=True)
            subprocess.run([str(binary)], check=True, capture_output=True)

    def test_bad_options(self):
        for args in [("--seed", "-1"), ("--seed", "18446744073709551616"),
                     ("--seed", "42oops"), ("--unknown", "x"), ("--seed", "1", "--seed", "2")]:
            self.run_source("int x;", *args, expected=2)

    def test_input_protected(self):
        self.src.write_text("int x;\n")
        for target in [self.src, self.root / "link.c", self.root / "hard.c"]:
            if target.name == "link.c": target.symlink_to(self.src)
            if target.name == "hard.c": target.hardlink_to(self.src)
            p = subprocess.run([TOOL, "transform", str(self.src), "-o", str(target)], capture_output=True)
            self.assertEqual(p.returncode, 2)
            self.assertEqual(self.src.read_text(), "int x;\n")


if __name__ == "__main__":
    unittest.main()
