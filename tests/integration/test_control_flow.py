"""Verify the actual emitted parity split, and reject a broken branch correction."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/differential"))
from run import compilers, execute
TOOL = str(Path(sys.argv.pop(1)).resolve())


class ControlFlow(unittest.TestCase):
    def test_splits_verified_and_executed_across_representations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, output, report = (root / n for n in ("source.c", "candidate.c", "report.json"))
            # Odd/even, wraparound, maximum scale, shadow-prone identifier, and k=0/1.
            source.write_text("unsigned int f(unsigned int csrd_value_0, unsigned int y){\n"
                              "unsigned int z = 3u * csrd_value_0 + 4294967295u * y;\n"
                              "return 2u*z + 0u*y + 1u*csrd_value_0;\n}\n")
            driver = root / "driver.c"
            driver.write_text('''#include <stdint.h>
unsigned int f(unsigned int, unsigned int);
int main(void) {
    uint32_t edge[] = {0u,1u,2u,3u,2147483647u,2147483648u,4294967294u,4294967295u};
    for(unsigned i=0;i<8;++i) for(unsigned j=0;j<8;++j) {
        uint32_t x=edge[i], y=edge[j];
        if(f(x,y) != 2u*(3u*x + 4294967295u*y)+x) return 1;
    }
    uint32_t x=42u;
    for(unsigned i=0;i<10000;++i) {
        x=x*1664525u+1013904223u;
        uint32_t y=x^0x12345678u;
        if(f(x,y) != 2u*(3u*x + 4294967295u*y)+x) return 2;
    }
    return 0;
}
''')
            for strategy in ("identity", "affine", "xor", "independent", "planned"):
                argv = [TOOL, "transform", source, "-o", output, "--control-flow", "split-scale",
                        "--strategy", strategy, "--seed", "42", "--report", report]
                execute(argv)
                record = json.loads(report.read_text())["functions"][0]
                self.assertEqual(record["verification"], "proved-under-model")
                self.assertEqual(record["control_flow"], "split-scale")
                self.assertEqual(record["split_scales"], 3)
                self.assertIn("if (", output.read_text())
                before = output.read_bytes(); execute(argv)
                self.assertEqual(before, output.read_bytes())
                for compiler, _, _ in compilers():
                    for optimization in ("-O0", "-O2"):
                        binary = root / "compare"
                        execute([compiler, "-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror",
                                 optimization, output, driver, "-o", binary])
                        execute([binary])

    def test_bad_correction_has_counterexample_and_ineligible_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, output, report = (root / n for n in ("source.c", "candidate.c", "report.json"))
            source.write_text("unsigned int f(unsigned int x){return 3u*x;}\n")
            execute([TOOL, "transform", source, "-o", output, "--strategy", "identity",
                     "--control-flow", "split-scale", "--report", report])
            self.assertIn("+ 3u;", output.read_text())
            output.write_text(output.read_text().replace("+ 3u;", "+ 2u;"))
            result = subprocess.run([TOOL, "verify", source, output, "--report", report], capture_output=True)
            self.assertEqual(result.returncode, 3)
            self.assertEqual(json.loads(report.read_text())["functions"][0]["verification"], "counterexample")
            source.write_text("unsigned int f(unsigned int x){return x^7u;}\n")
            execute([TOOL, "transform", source, "-o", output, "--control-flow", "split-scale", "--report", report])
            self.assertEqual(json.loads(report.read_text())["functions"][0]["split_scales"], 0)
            result = subprocess.run([TOOL, "transform", source, "-o", output, "--control-flow", "arbitrary"], capture_output=True)
            self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
