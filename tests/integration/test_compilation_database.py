"""Real compile command settings must survive freezing, transformation and checking."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

TOOL = str(Path(sys.argv.pop(1)).resolve())


class CompilationDatabase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.work = self.root / "build dir"
        self.work.mkdir()
        self.source = self.root / "source.c"
        self.source.write_text("unsigned long f(unsigned long x){x=3ul*x+11ul;return x;}\n")
        self.database = self.root / "compile_commands.json"
        self.output = self.root / "candidate.i"
        self.report = self.root / "report.json"

    def tearDown(self):
        self.temp.cleanup()

    def entry(self, *extra):
        return {"directory": str(self.work), "file": "../source.c", "output": "source.o",
                "arguments": ["clang", "-std=c11", *map(str, extra), "-c", "../source.c", "-o", "source.o"]}

    def save(self, entries):
        self.database.write_text(json.dumps(entries))

    def call(self, action, input=None, *flags, code=0):
        args = [TOOL, action, str(input or self.source), "--compilation-database", str(self.database),
                "--report", str(self.report), *map(str, flags)]
        if action in ("transform", "preprocess"): args += ["-o", str(self.output)]
        result = subprocess.run(args, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, code, result.stderr)
        return json.loads(self.report.read_text()) if code == 0 else result

    def test_target_from_cross_compiler_name_and_reparse(self):
        entry = self.entry()
        entry["arguments"][0] = "x86_64-w64-mingw32-gcc"
        self.save([entry])
        report = self.call("transform", None, "--scope", "private-regions", "--seed", "42")
        self.assertIn("windows", report["target"])
        self.assertEqual(report["functions"][0]["private_regions"][0]["long_bits"], 32)
        self.assertEqual(report["functions"][0]["verification"], "proved-under-model")
        self.assertEqual(report["frontend"]["compiler_arguments"], report["frontend"]["candidate_compiler_arguments"])
        self.assertEqual(report["compilation_command"]["directory"], str(self.work))
        self.assertEqual(report["compilation_command"]["database_sha256"], hashlib.sha256(self.database.read_bytes()).hexdigest())

    def test_command_string_relative_include_and_forced_header(self):
        includes = self.work / "include space"
        includes.mkdir()
        (includes / "settings.h").write_text("#define OFFSET 17ul\n")
        (self.work / "forced.h").write_text("#define ENABLED 1\n")
        self.source.write_text('#include "settings.h"\n#if !ENABLED || VALUE != 5\n#error configuration lost\n#endif\n'
                               'unsigned long f(unsigned long x){x=x+OFFSET;return x;}\n')
        entry = self.entry("-Iinclude space", "-include", "forced.h", "-DVALUE=5", "--target=x86_64-unknown-linux-gnu")
        entry["command"] = shlex.join(entry.pop("arguments"))
        self.save([entry])
        preprocessed = self.call("preprocess")
        original = self.output.read_bytes()
        self.assertEqual(preprocessed["candidate_sha256"], hashlib.sha256(original).hexdigest())
        self.assertIn("17ul", original.decode())
        frozen = self.root / "frozen.i"
        frozen.write_bytes(original)
        transformed = self.call("transform", frozen, "--scope", "private-regions", "--compile-command", "0")
        self.assertEqual(transformed["source_sha256"], preprocessed["candidate_sha256"])
        self.assertEqual(transformed["functions"][0]["verification"], "proved-under-model")
        self.assertEqual(transformed["functions"][0]["private_regions"][0]["long_bits"], 64)

    def test_nested_response_files_and_no_build_side_effects(self):
        (self.work / "nested.rsp").write_text("-std=c11 -DVALUE=19ul -funsigned-char")
        (self.work / "outer.rsp").write_text("@nested.rsp -MMD -MP -MF should-not-exist.d")
        self.source.write_text("#if VALUE != 19ul\n#error missing response flags\n#endif\n"
                               "char f(char x){x=x+1;return x;}\n")
        self.save([self.entry("@outer.rsp", "--target=x86_64-unknown-linux-gnu")])
        (self.work / "source.o").write_text("existing object\n")
        report = self.call("transform", None, "--scope", "private-regions")
        self.assertFalse(report["functions"][0]["private_regions"][0]["plain_char_signed"])
        self.assertEqual((self.work / "source.o").read_text(), "existing object\n")
        self.assertFalse((self.work / "should-not-exist.d").exists())
        self.assertFalse(any(a.startswith("@") for a in report["compilation_command"]["expanded_arguments"]))

    def test_duplicate_configurations_require_explicit_index(self):
        self.save([self.entry("--target=x86_64-unknown-linux-gnu"), self.entry("--target=x86_64-w64-windows-gnu")])
        self.call("analyze", code=2)
        report = self.call("analyze", None, "--compile-command", "1", "--scope", "private-regions")
        self.assertEqual(report["compilation_command"]["index"], 1)
        self.assertIn("windows", report["target"])
        self.call("analyze", None, "--compile-command", "2", code=2)

    def test_unsupported_semantics_and_opaque_state_rejected(self):
        for flag, code in [("-fwrapv", 1), ("-ftrapv", 1), ("-std=c99", 1), ("-fopenmp", 1),
                           ("-fplugin=missing.so", 2), ("-include-pch=missing.pch", 2), ("-fmodules", 2),
                           ("--config=missing.cfg", 2), ("-specs=missing.specs", 2)]:
            with self.subTest(flag=flag):
                self.save([self.entry(flag)])
                self.output.write_text("existing candidate\n")
                self.call("transform", None, "--scope", "private-regions", code=code)
                self.assertEqual(self.output.read_text(), "existing candidate\n")

    def test_unknown_semantic_pragmas_and_attributes_are_not_ignored(self):
        for source in ['#pragma GCC optimize("wrapv")\nint f(int x){int y=x+1;return y;}\n',
                       'int __attribute__((optimize("wrapv"))) f(int x){int y=x+1;return y;}\n']:
            with self.subTest(source=source):
                self.source.write_text(source)
                self.save([self.entry()])
                self.output.write_text("existing candidate\n")
                self.call("transform", None, "--scope", "private-regions", code=1)
                self.assertEqual(self.output.read_text(), "existing candidate\n")

    def test_verify_reuses_selected_entry_for_different_file(self):
        self.source.write_text("typedef unsigned int uint32_t; uint32_t f(uint32_t x){return 3u*x+11u;}\n")
        candidate = self.root / "different.c"
        candidate.write_text(self.source.read_text())
        self.save([self.entry("--target=x86_64-w64-windows-gnu")])
        proc = subprocess.run([TOOL, "verify", str(self.source), str(candidate), "--compilation-database", str(self.database),
                               "--report", str(self.report)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(self.report.read_text())["functions"][0]["verification"], "proved-under-model")

    def test_database_cannot_be_overwritten_or_silently_overridden(self):
        self.save([self.entry()])
        expected = self.database.read_bytes()
        self.output = self.database
        self.call("transform", code=2)
        self.assertEqual(self.database.read_bytes(), expected)
        self.call("analyze", None, "--target", "x86_64-unknown-linux-gnu", code=2)

    def test_original_filename_spelling_is_preserved_in_preprocessing(self):
        self.source.write_text("const char *file_name = __FILE__;\nunsigned f(unsigned x){return x;}\n")
        self.save([self.entry("--target=x86_64-unknown-linux-gnu")])
        self.call("preprocess")
        self.assertIn('"../source.c"', self.output.read_text())

    def test_metadata_does_not_claim_source_validation(self):
        self.source.write_text("not valid C\n")
        self.save([self.entry("--target=x86_64-unknown-linux-gnu")])
        report = self.call("compile-command")
        self.assertEqual(report["functions"], [])
        self.assertFalse(report["output_written"])
        self.assertIn("not-verified", report["verification"])
        self.assertEqual(report["compilation_command"]["source"], str(self.source))


if __name__ == "__main__":
    unittest.main()
