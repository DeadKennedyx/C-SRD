"""Original-compiler headers must survive the newer frontend without rewriting.

Clang 18's rejection is a tested coverage boundary, not a successful transform.
The positive path uses GCC for preprocessing and final compilation/execution.
"""
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import project_fixture
import transform_project

TOOL = Path(sys.argv.pop(1)).resolve()


@unittest.skipUnless(sys.platform.startswith("linux") and platform.libc_ver()[0] == "glibc", "Linux GCC/glibc compatibility test")
class GccHeaders(unittest.TestCase):
    def setUp(self):
        self.gcc = shutil.which("gcc")
        if not self.gcc or "gcc" not in subprocess.check_output([self.gcc, "--version"], text=True).lower():
            self.skipTest("GNU GCC required")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        probe, report = self.root / "probe.c", self.root / "probe.json"
        probe.write_text("unsigned probe(unsigned x){return x;}\n")
        self.run_ok([TOOL, "analyze", probe, "--report", report])
        self.major = int(re.search(r"clang version (\d+)", json.loads(report.read_text())["clang"]).group(1))

    def run_ok(self, arguments):
        process = subprocess.run(list(map(str, arguments)), capture_output=True, text=True, timeout=120)
        self.assertEqual(process.returncode, 0, process.stderr)
        return process

    def test_frozen_headers_preserved_or_conservatively_rejected(self):
        source, frozen = self.root / "program.c", self.root / "program.i"
        source.write_text('''#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
uint32_t adjusted(uint32_t x) { uint32_t y = x + 17u; y = 3u*y + 5u; return y; }
int main(void) {
    uint32_t *p = malloc(4u*sizeof(*p));
    if (!p) return 77;
    p[0]=0u; p[1]=1u; p[2]=UINT32_MAX; p[3]=UINT32_C(0x80000000);
    for (unsigned i=0u;i<4u;++i) printf("%u\\n", (unsigned)adjusted(p[i]));
    free(p);
    return 0;
}
''')
        self.run_ok([self.gcc, "-std=c11", "-E", source, "-o", frozen])
        original = frozen.read_bytes()
        # The known fixture's prefix includes all GCC-expanded system declarations.
        prefix = original.split(b"uint32_t adjusted(", 1)[0]
        self.assertIn(b"__malloc__", prefix)
        baseline = self.root / "original"
        self.run_ok([self.gcc, "-std=c11", "-O2", frozen, "-o", baseline])
        expected = "".join(f"{((x+17)*3+5)&0xffffffff}\n" for x in (0,1,0xffffffff,0x80000000))
        self.assertEqual(self.run_ok([baseline]).stdout, expected)
        for scope in ("private-regions", "outline-regions", "control-regions"):
            with self.subTest(scope=scope):
                candidate, report = self.root / (scope+".i"), self.root / (scope+".json")
                candidate.write_text("existing output must survive a rejected parse\n")
                before = candidate.read_bytes()
                result = subprocess.run([str(TOOL), "transform", str(frozen), "-o", str(candidate),
                    "--scope", scope, "--seed", "42", "--report", str(report)], capture_output=True, text=True, timeout=120)
                if self.major < 21:
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn("attribute takes no arguments", result.stderr)
                    self.assertEqual(candidate.read_bytes(), before)
                    continue
                self.assertEqual(result.returncode, 0, result.stderr)
                data = json.loads(report.read_text())
                row = next(f for f in data["functions"] if f["function"] == "adjusted")
                self.assertEqual(row["verification"], "proved-under-model")
                self.assertNotEqual(row["status"], "unchanged")
                self.assertTrue(candidate.read_bytes().startswith(prefix), "system declarations were rewritten")
                self.assertEqual(frozen.read_bytes(), original)
                for level in ("-O0", "-O2"):
                    binary = self.root / (scope+level)
                    self.run_ok([self.gcc, "-std=c11", level, candidate, "-o", binary])
                    self.assertEqual(self.run_ok([binary]).stdout, expected)

    def test_full_gcc_multifile_project(self):
        if self.major < 21:
            self.skipTest("positive whole-project path requires the newer frontend")
        spec = project_fixture.create(self.root / "project", self.gcc, ["-O2"])
        config = json.loads(spec.read_text())
        config["variants"] += [{"name": "affine_outline_control", "passes": [
            {"scope": "private-regions", "strategy": "affine", "seed": 42},
            {"scope": "outline-regions", "seed": 42},
            {"scope": "control-regions", "seed": 42}]}]
        spec.write_text(json.dumps(config))
        result = transform_project.build_project(TOOL, spec, self.root / "artifacts")
        self.assertEqual(result["status"], "built; application behavior not yet tested")
        self.assertEqual(len(result["units"]), 3)
        self.assertTrue(all(unit["passes"] for unit in result["units"]))
        self.assertTrue(all(unit["transformation_status"] == "selected" for unit in result["units"]))
        self.assertTrue(all(len(unit["passes"]["affine_outline_control"]) == 3 for unit in result["units"]))
        self.assertGreater(result["units"][2]["passes"]["affine_outline_control"][2]["control_nodes"], 0)
        for variant, build in result["builds"].items():
            with self.subTest(variant=variant):
                binary = build["links"][0]["path"]
                for seed, count, repeats in ((0,0,0),(0xffffffff,1,1),(0xffffffff,64,3),(17,7,5)):
                    # GCC selects the non-Clang branch of include/settings.h.
                    project_fixture.check(binary, self.root, seed, count, repeats, 13)
                missing = self.root / "missing" / "output.txt"
                for arguments, code in (([],2), (["0","65","1",str(missing)],3),
                        (["0","1","10000001",str(missing)],3), (["0","1","1",str(missing)],5)):
                    process = subprocess.run([binary, *arguments], capture_output=True, timeout=30)
                    self.assertEqual((process.returncode, process.stdout, process.stderr), (code,b"",b""))
                    self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
