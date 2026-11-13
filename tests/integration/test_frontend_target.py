"""Target/SDK propagation, preprocessing provenance and cross-ABI regressions."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOL = str(Path(sys.argv.pop(1)).resolve())
WINDOWS = "x86_64-w64-windows-gnu"
LINUX = "x86_64-unknown-linux-gnu"


class FrontendTarget(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.input = self.root / "input.c"
        self.output = self.root / "output.c"
        self.report = self.root / "report.json"

    def tearDown(self):
        self.temp.cleanup()

    def call(self, *args, code=0):
        result = subprocess.run([TOOL, *map(str, args)], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, code, result.stderr)
        return result

    def transform(self, source, target):
        self.input.write_text(source)
        self.call("transform", self.input, "-o", self.output, "--target", target,
                  "--scope", "private-regions", "--seed", "42", "--report", self.report)
        document = json.loads(self.report.read_text())
        self.assertEqual(document["frontend"]["compiler_arguments"], document["frontend"]["candidate_compiler_arguments"])
        self.assertNotIn("-isysroot", document["frontend"]["compiler_arguments"])
        self.assertEqual(document["functions"][0]["verification"], "proved-under-model")
        return document

    def test_lp64_and_llp64_reparsed_using_requested_target(self):
        source = "unsigned long f(unsigned long x){unsigned long y=x+1ul;y=3ul*y;return y;}\n"
        outputs = {}
        for target, bits in [(WINDOWS, 32), (LINUX, 64)]:
            with self.subTest(target=target):
                doc = self.transform(source, target)
                frame = doc["functions"][0]["private_regions"][0]
                self.assertEqual(frame["long_bits"], bits)
                self.assertTrue(all(b["value_bits"] == bits for b in frame["bindings"]))
                self.assertIn(f"sizeof(long)=={bits//8}", self.output.read_text())
                outputs[target] = self.output.read_text()
        self.assertNotEqual(outputs[WINDOWS], outputs[LINUX])

    def test_verify_and_analyze_use_target(self):
        source = "typedef unsigned int uint32_t; uint32_t f(uint32_t x){return x+11u;}\n"
        self.input.write_text(source)
        self.output.write_text(source)
        self.call("verify", self.input, self.output, "--target", WINDOWS, "--report", self.report)
        doc = json.loads(self.report.read_text())
        self.assertIn("windows", doc["target"])
        self.assertEqual(doc["frontend"]["compiler_arguments"], doc["frontend"]["candidate_compiler_arguments"])
        self.call("analyze", self.input, "--target", WINDOWS, "--report", self.report)
        self.assertIn("windows", json.loads(self.report.read_text())["target"])

    def test_preprocess_includes_definitions_and_provenance(self):
        directory = self.root / "include with spaces"
        directory.mkdir()
        header = directory / "settings.h"
        header.write_text("#if FLAG != 7\n#error missing build configuration\n#endif\n#define STEP(x) ((x)+OFFSET)\n")
        self.input.write_text("#include <settings.h>\nunsigned long f(unsigned long x){x=STEP(x);return x;}\n")
        frozen = self.root / "frozen.i"
        options = ["--target", WINDOWS, "--include-dir", directory, "--define", "FLAG=7", "--define", "OFFSET=11ul"]
        self.call("preprocess", self.input, "-o", frozen, "--report", self.report, *options)
        doc = json.loads(self.report.read_text())
        self.assertTrue(doc["output_written"])
        self.assertEqual(doc["source_sha256"], hashlib.sha256(self.input.read_bytes()).hexdigest())
        self.assertEqual(doc["candidate_sha256"], hashlib.sha256(frozen.read_bytes()).hexdigest())
        self.assertIn({"path": str(header), "sha256": hashlib.sha256(header.read_bytes()).hexdigest()}, doc["dependencies"])
        self.assertEqual(doc["frontend"]["definitions"], ["FLAG=7", "OFFSET=11ul"])
        self.assertIn("not-proved", doc["verification"])
        self.assertNotIn("STEP(x)", frozen.read_text())
        self.call("transform", frozen, "-o", self.output, "--scope", "private-regions", "--target", WINDOWS,
                  "--report", self.report)
        doc = json.loads(self.report.read_text())
        self.assertEqual(doc["functions"][0]["status"], "regions-transformed")
        self.assertEqual(doc["functions"][0]["private_regions"][0]["long_bits"], 32)

    def test_custom_sysroot_without_host_sdk(self):
        root = self.root / "target SDK"
        (root / "include").mkdir(parents=True)
        (root / "include/platform.h").write_text("typedef unsigned long platform_word;\n")
        self.input.write_text("#include <platform.h>\nplatform_word f(platform_word x){x=x+1ul;return x;}\n")
        self.call("transform", self.input, "-o", self.output, "--target", WINDOWS, "--sysroot", root,
                  "--scope", "private-regions", "--report", self.report)
        doc = json.loads(self.report.read_text())
        self.assertEqual(doc["frontend"]["requested_sysroot"], str(root))
        self.assertIn("--sysroot="+str(root), doc["frontend"]["compiler_arguments"])
        self.assertNotIn("-isysroot", doc["frontend"]["compiler_arguments"])
        self.assertEqual(doc["functions"][0]["private_regions"][0]["long_bits"], 32)

    def test_failures_preserve_output(self):
        self.input.write_text("unsigned f(unsigned x){return x;}\n")
        for flags in [("--target", ""), ("--target", WINDOWS, "--target", LINUX),
                      ("--sysroot", self.root / "missing"), ("--include-dir", ""), ("--define", "")]:
            with self.subTest(flags=flags):
                self.output.write_text("existing output\n")
                self.call("transform", self.input, "-o", self.output, *flags, code=2)
                self.assertEqual(self.output.read_text(), "existing output\n")
        self.call("transform", self.input, "-o", self.output, "--target", "nonexistent-unknown-none", code=1)
        self.assertEqual(self.output.read_text(), "existing output\n")
        self.call("preprocess", self.input, "-o", self.output, code=2)
        frozen = self.root / "frozen.i"
        frozen.write_text("existing preprocessed file\n")
        self.input.write_text("#error intentionally invalid configuration\n")
        self.call("preprocess", self.input, "-o", frozen, code=1)
        self.assertEqual(frozen.read_text(), "existing preprocessed file\n")

    def test_mingw_headers_and_compilation(self):
        gcc = shutil.which("x86_64-w64-mingw32-gcc")
        if not gcc: self.skipTest("MinGW cross compiler not installed; other target tests need no SDK")
        sysroot = subprocess.check_output([gcc, "-print-sysroot"], text=True).strip()
        if not sysroot or not Path(sysroot).is_dir(): self.skipTest("MinGW sysroot unavailable")
        self.input.write_text("#include <stdint.h>\n_Static_assert(sizeof(long)==4,\"LLP64\");\n"
                              "uint64_t f(uint64_t x){x=3ull*x+11ull;return x;}\n")
        frozen, candidate = self.root / "frozen.i", self.root / "candidate.i"
        flags = ["--target", WINDOWS, "--sysroot", sysroot]
        self.call("preprocess", self.input, "-o", frozen, *flags)
        self.call("transform", frozen, "-o", candidate, "--scope", "private-regions", "--report", self.report, *flags)
        function = next(f for f in json.loads(self.report.read_text())["functions"] if f["function"] == "f")
        self.assertEqual(function["verification"], "proved-under-model")
        proc = subprocess.run([gcc, "-std=c11", "-O2", "-c", str(candidate), "-o", str(self.root / "candidate.o")],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
