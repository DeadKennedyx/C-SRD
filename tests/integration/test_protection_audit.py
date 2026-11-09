"""Exercise the audit's evidence boundaries with real Clang/GCC and the validator."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TOOL = str(Path(sys.argv.pop(1)).resolve())
AUDIT = ROOT / "tools/audit_protection.py"
sys.path.insert(0, str(ROOT / "tools"))
from audit_protection import assert_snapshot, file_hash, AuditError


def compiler_tools():
    requested = os.environ.get("CSRD_TEST_COMPILERS")
    candidates = requested.split(":") if requested else ["clang", "clang-18", "gcc-16", "gcc-15", "gcc-14", "gcc"]
    families = {}
    for name in candidates:
        path = shutil.which(name)
        if not path:
            continue
        version = subprocess.run([path, "--version"], text=True, capture_output=True, check=True).stdout
        family = "clang" if "clang" in version.lower() else "gcc" if "Free Software Foundation" in version else None
        if family and family not in families:
            families[family] = path
    return families


def find_objdump():
    for name in [os.environ.get("CSRD_OBJDUMP", ""), "llvm-objdump", "llvm-objdump-18",
                 "/opt/homebrew/opt/llvm/bin/llvm-objdump"]:
        if name and shutil.which(name):
            return shutil.which(name)
    raise RuntimeError("llvm-objdump required for protection audit tests (set CSRD_OBJDUMP)")


class ProtectionAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compilers = compiler_tools()
        if not cls.compilers:
            raise RuntimeError("a Clang/GCC compiler is required")
        if os.environ.get("CSRD_REQUIRE_BOTH_COMPILERS") == "1" and set(cls.compilers) != {"clang", "gcc"}:
            raise RuntimeError("both real Clang and GNU GCC are required")
        cls.objdump = find_objdump()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.original = self.root / "original.c"
        self.candidate = self.root / "candidate.c"
        self.original.write_text("#include <stdint.h>\nuint32_t calculate(uint32_t x,uint32_t y) {uint32_t s=x+y; return 3u*s+11u;}\n")
        self.candidate.write_bytes(self.original.read_bytes())

    def audit(self, name="audit", extra=(), expected=0):
        directory = self.root / name
        command = [sys.executable, str(AUDIT), str(self.original), str(self.candidate),
                   "--csrd", TOOL, "--objdump", self.objdump, "--output-dir", str(directory)]
        for compiler in self.compilers.values():
            command.extend(["--compiler", compiler])
        result = subprocess.run([*command, *extra], text=True, capture_output=True, timeout=120)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        path = directory / "audit.json"
        return json.loads(path.read_text()) if path.exists() else None

    def test_identity_control_at_both_optimization_levels(self):
        report = self.audit()
        self.assertEqual(report["status"], "completed")
        self.assertFalse(report["source_bytes_differ"])
        self.assertEqual(report["summary"]["configurations"], 2 * len(self.compilers))
        self.assertEqual(report["summary"]["different_code_sections"], 0)
        self.assertEqual(report["claims"]["source_equivalence"], "proved-under-model")
        self.assertEqual(report["claims"]["reverse_engineering_effort"], "not-assessed")
        self.assertEqual(report["claims"]["memory_exposure"], "not-assessed")
        self.assertEqual(report["claims"]["confidentiality"], "not-established")
        for config in report["configurations"]:
            self.assertEqual(config["observation"], "no-code-section-byte-difference")
            self.assertEqual(config["text_size_ratio"], 1)
            self.assertGreater(config["objects"]["original"]["text_bytes"], 0)

    def test_actual_generated_candidate_and_artifact_binding(self):
        subprocess.run([TOOL, "transform", str(self.original), "-o", str(self.candidate),
                        "--seed", "42"], text=True, capture_output=True, check=True)
        report = self.audit()
        self.assertTrue(report["source_bytes_differ"])
        self.assertEqual(report["inputs"]["candidate"]["sha256"], file_hash(self.candidate))
        self.assertEqual(report["verification"]["candidate_sha256"], file_hash(self.candidate))
        # Optimizer behavior varies by version/target: never assert a desired survival result.
        for config in report["configurations"]:
            self.assertEqual(config["status"], "completed")
            left, right = (config["objects"][key] for key in ["original", "candidate"])
            self.assertEqual(config["code_section_bytes_identical"], left["text_sha256"] == right["text_sha256"])
            for obj in config["objects"].values():
                self.assertEqual(obj["object_sha256"], file_hash(self.root / "audit" / obj["path"]))
            for binding in config["build_validation"].values():
                self.assertEqual(binding["verification"], "proved-under-model")
                self.assertEqual(binding["preprocessed_sha256"], file_hash(self.root / "audit" / binding["preprocessed_path"]))
        self.assertTrue(any("--full-contents" in c["argv"] for c in report["commands"]))

    def test_behavior_change_is_rejected_before_compilation(self):
        self.candidate.write_text(self.original.read_text().replace("+11u", "+12u"))
        report = self.audit(expected=1)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["claims"]["source_equivalence"], "counterexample")
        self.assertEqual(report["configurations"], [])
        proof = report["verification"]["functions"][0]["proof"]
        self.assertNotEqual(proof["original_output"], proof["candidate_output"])

    def test_unsupported_and_extra_functions_are_rejected(self):
        for index, source in enumerate([
            "#include <stdint.h>\nuint32_t calculate(uint32_t x,uint32_t y){return x*y;}\n",
            self.original.read_text() + "uint32_t extra(uint32_t x){return x+1u;}\n",
        ]):
            self.candidate.write_text(source)
            report = self.audit(name=f"rejected-{index}", expected=1)
            self.assertIn("exactly one supported pure function", report["error"])
            self.assertEqual(report["configurations"], [])

    def test_existing_evidence_is_never_overwritten(self):
        directory = self.root / "audit"
        directory.mkdir()
        sentinel = directory / "audit.json"
        sentinel.write_text('{"sentinel":true}')
        self.audit(expected=2)
        self.assertEqual(sentinel.read_text(), '{"sentinel":true}')

    def test_compile_failure_is_not_a_successful_audit(self):
        # A common unused parameter is accepted by the source model but rejected by
        # the fixed warning-clean compiler protocol. No fake compiler is involved.
        source = "#include <stdint.h>\nuint32_t choose(uint32_t x,uint32_t y){return x;}\n"
        self.original.write_text(source)
        self.candidate.write_text(source)
        report = self.audit(expected=1)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["claims"]["source_equivalence"], "proved-under-model")
        self.assertNotIn("summary", report)
        self.assertEqual(report["configurations"][0]["status"], "incomplete")

    def test_single_parameter_has_no_kernel_name_requirement(self):
        source = "#include <stdint.h>\nuint32_t named_freely(uint32_t x){return x+11u;}\n"
        self.original.write_text(source)
        self.candidate.write_text(source)
        report = self.audit(extra=["--optimization", "O2"])
        self.assertEqual(report["function"], "named_freely")
        self.assertEqual(report["parameter_count"], 1)
        self.assertEqual(report["summary"]["configurations"], len(self.compilers))

    def test_changed_snapshot_cannot_reuse_evidence(self):
        snapshot = {str(self.original): file_hash(self.original)}
        self.original.write_text(self.original.read_text().replace("+11u", "+12u"))
        with self.assertRaisesRegex(AuditError, "changed during audit"):
            assert_snapshot(snapshot)

    def test_optimization_dependent_preprocessing_is_rejected(self):
        source = ("#include <stdint.h>\n#if defined(__OPTIMIZE__)\n"
                  "uint32_t f(uint32_t x){return x+2u;}\n#else\n"
                  "uint32_t f(uint32_t x){return x+1u;}\n#endif\n")
        self.original.write_text(source)
        self.candidate.write_text(source)
        report = self.audit(extra=["--optimization", "O2"], expected=1)
        self.assertEqual(report["claims"]["source_equivalence"], "proved-under-model")
        self.assertEqual(report["status"], "failed")
        config = report["configurations"][0]
        self.assertEqual(config["build_validation"]["original"]["verification"], "counterexample")
        self.assertEqual(config["objects"], {})

    def test_zero_code_bytes_do_not_count_as_surviving_or_erased(self):
        source = "#include <stdint.h>\ninline uint32_t f(uint32_t x){return x+1u;}\n"
        self.original.write_text(source)
        self.candidate.write_text(source)
        report = self.audit(extra=["--optimization", "O2"], expected=1)
        self.assertEqual(report["status"], "failed")
        self.assertNotIn("summary", report)

    def test_local_include_environment_mismatch_is_rejected(self):
        source = '#include "local.h"\nuint32_t f(uint32_t x){return x+1u;}\n'
        (self.root / "local.h").write_text("#include <stdint.h>\n")
        other = self.root / "other"
        other.mkdir()
        (other / "local.h").write_text("#include <stdint.h>\n/* distinct header snapshot */\n")
        self.original.write_text(source)
        self.candidate = other / "candidate.c"
        self.candidate.write_text(source)
        report = self.audit(expected=1)
        self.assertIn("header environments differ", report["error"])
        self.assertEqual(report["configurations"], [])


if __name__ == "__main__":
    unittest.main()
