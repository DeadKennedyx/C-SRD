import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import project_fixture
import transform_project

TOOL = Path(sys.argv.pop(1)).resolve()


class ProjectBuild(unittest.TestCase):
    def test_multifile_build_and_composed_passes(self):
        compiler = shutil.which("clang-18") or shutil.which("clang")
        if compiler is None:
            self.skipTest("Clang unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            spec = project_fixture.create(tmp / "project", compiler, ["-O2"])
            configured = json.loads(spec.read_text())
            affine = {"scope": "private-regions", "strategy": "affine", "seed": 42}
            control = {"scope": "control-regions", "seed": 42}
            outline = {"scope": "outline-regions", "seed": 42}
            configured["variants"] += [{"name": "control", "passes": [control]},
                                       {"name": "affine_control", "passes": [affine, control]},
                                       {"name": "control_affine", "passes": [control, affine]},
                                       {"name": "outline", "passes": [outline]},
                                       {"name": "affine_outline_control", "passes": [affine, outline, control]}]
            spec.write_text(json.dumps(configured))
            result = transform_project.build_project(TOOL, spec, tmp / "artifacts")
            self.assertEqual(result["status"], "built; application behavior not yet tested")
            self.assertEqual(len(result["units"]), 3)
            self.assertGreater(sum(unit["passes"]["affine"][0]["operations_transformed"] for unit in result["units"]), 0)
            self.assertTrue(all(len(unit["passes"]["affine_identity"]) == 2 for unit in result["units"]))
            self.assertGreater(sum(unit["passes"]["affine_identity"][1]["operations_transformed"] for unit in result["units"]), 0)
            self.assertGreater(sum(unit["passes"]["control"][0]["control_nodes"] for unit in result["units"]), 0)
            self.assertGreater(sum(unit["passes"]["outline"][0]["outlined_expressions"] for unit in result["units"]), 0)
            self.assertTrue(all(len(unit["passes"]["affine_outline_control"]) == 3 for unit in result["units"]))
            self.assertTrue(all(len(unit["passes"]["control_affine"]) == 2 for unit in result["units"]))
            self.assertTrue(all(len(unit["passes"]["affine_control"]) == 2 for unit in result["units"]))
            for variant, build in result["builds"].items():
                with self.subTest(variant=variant):
                    for seed, count, repeats in [(0, 0, 0), (0xffffffff, 1, 1), (0xffffffff, 64, 3), (17, 7, 5)]:
                        project_fixture.check(build["links"][0]["path"], tmp, seed, count, repeats, 11)
            self.assertFalse(list((tmp / "project/build").glob("*.o")))
            with self.assertRaises(FileExistsError):
                transform_project.build_project(TOOL, spec, tmp / "artifacts")

    def test_replay_rejects_unmodeled_build_actions(self):
        compiler = shutil.which("clang-18") or shutil.which("clang")
        if compiler is None:
            self.skipTest("Clang unavailable")
        for flag in ("-save-temps", "-Wp,-DOTHER", "-fprofile-generate", "-Xclang", "--config=other.cfg"):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                transform_project.adapt_compile([compiler, "-std=c11", flag, "-c", "unit.c"], Path("/tmp/unit.c"), "/tmp", "/tmp/out.o")
        with self.assertRaises(ValueError):
            transform_project.link_arguments({"arguments": [compiler, "-o", "outside", "-o", "{output}", "{object:0}"]}, "/tmp", {0: "/tmp/unit.o"}, "/tmp/out")

    def test_failure_manifest_does_not_report_success(self):
        compiler = shutil.which("clang-18") or shutil.which("clang")
        if compiler is None:
            self.skipTest("Clang unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            spec = project_fixture.create(tmp / "project", compiler, ["-fwrapv"])
            with self.assertRaises(RuntimeError):
                transform_project.build_project(TOOL, spec, tmp / "artifacts")
            report = json.loads((tmp / "artifacts/manifest.json").read_text())
            self.assertEqual(report["status"], "failed")
            self.assertIn("analyze-0", report["error"])
            self.assertFalse(report["builds"])

    def test_explicitly_excluded_unit_is_preserved_and_not_verified(self):
        compiler = shutil.which("clang-18") or shutil.which("clang")
        if compiler is None:
            self.skipTest("Clang unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            spec = project_fixture.create(tmp / "project", compiler, ["-O2"])
            config = json.loads(spec.read_text())
            config["transform_commands"] = [0, 1]
            spec.write_text(json.dumps(config))
            database = tmp / "project/build/compile_commands.json"
            entries = json.loads(database.read_text())
            entries[2]["command"] += " -fwrapv"
            database.write_text(json.dumps(entries))
            result = transform_project.build_project(TOOL, spec, tmp / "artifacts")
            excluded = result["units"][2]
            self.assertIn("explicitly-excluded", excluded["transformation_status"])
            self.assertEqual(excluded["passes"], {})
            for build in result["builds"].values():
                project_fixture.check(build["links"][0]["path"], tmp, 0xffffffff, 64, 3, 11)


if __name__ == "__main__":
    unittest.main()
