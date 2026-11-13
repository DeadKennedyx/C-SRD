"""Independent buffer oracles and finite trace-fit controls."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from audit_protection import file_hash
from buffer_observation_cases import cases, driver, expected, LAYOUTS, FUNCTIONS
from fit_buffer_traces import run as fit


class BufferRuntime(unittest.TestCase):
    def test_training_targets_have_odd_differences_and_holdout_stays_frozen(self):
        current, previous = cases(), cases("seeded-v1")
        self.assertEqual(current[4:], previous[4:])
        missing = 0
        for function in sorted(FUNCTIONS):
            for p, q in LAYOUTS:
                for protocol, rows in (("basis-parity-v2", current), ("seeded-v1", previous)):
                    targets = [expected(function, c["memory"], p, q, c["x"])["targets"] for c in rows[:4]]
                    for target in targets[0]:
                        parities = {t[target] & 1 for t in targets}
                        if protocol == "basis-parity-v2": self.assertEqual(parities, {0, 1}, (function, p, q, target))
                        else: missing += len(parities) != 2
        self.assertEqual(missing, 14)

    def test_oracles_match_actual_c_for_aliases_and_edges(self):
        configured = os.environ.get("CSRD_TEST_COMPILERS")
        compilers = configured.split(os.pathsep) if configured else [shutil.which("clang") or shutil.which("cc")]
        self.assertTrue(compilers[0], "C compiler required")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for compiler in compilers:
                for function in sorted(FUNCTIONS):
                    params = [{"kind": "uint32-buffer", "read_only": function == "buffer_const"},
                              {"kind": "uint32-buffer", "read_only": function == "buffer_update"},
                              {"kind": "uint32", "read_only": False}]
                    harness = root / "harness.c"; harness.write_text(driver(function, params))
                    source = ROOT / ("benchmarks/arithmetic/buffer_update.c" if function == "buffer_update" else "tests/fixtures/buffers.c")
                    binary = root / "program"
                    subprocess.run([compiler, "-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", "-O2",
                                    harness, source, "-o", binary], check=True, capture_output=True)
                    for p, q in LAYOUTS:
                        for case in cases():
                            oracle = expected(function, case["memory"], p, q, case["x"])
                            data = " ".join(map(str, [p, q, case["x"], *case["memory"]])) + "\n"
                            result = subprocess.run([binary], input=data, text=True, capture_output=True, check=True)
                            self.assertEqual(list(map(int, result.stdout.split())), [oracle["return_value"], *oracle["final_memory"]],
                                             (compiler, function, p, q, case["x"]))

    def test_fit_separates_success_false_and_missing_locations(self):
        targets = [3, 8, 29, 101, 0xffffffff, 0x80000000]
        with tempfile.TemporaryDirectory() as tmp:
            config = {"traces": [], "targets": {"sum": targets}}
            for i, target in enumerate(targets):
                values = {"reg:x1": (7*target+19) & 0xffffffff, "caller:4": target,
                          "reg:x2": ((9*target+17) if i < 4 else 0) & 0xffffffff}
                if i < 4: values["stack+0"] = (3*target+1) & 0xffffffff
                trace = {"status": "completed", "stack_read_failures": 0,
                         "samples": [{"offset": 4, "visit": 0, "values": values}]}
                path = Path(tmp) / f"{i}.json"; path.write_text(json.dumps(trace))
                config["traces"].append({"path": str(path), "sha256": file_hash(path),
                                         "split": "training" if i < 4 else "heldout"})
            result = fit(config)["targets"]["sum"]
            self.assertEqual(result["recovery"]["validated_models"], 2)
            self.assertEqual(result["recovery"]["false_models"], 1)
            self.assertEqual(result["recovery"]["inconclusive_models"], 1)
            self.assertEqual(result["by_scope"]["caller-memory"]["validated_locations"], 1)
            self.assertEqual(result["by_scope"]["register"]["validated_locations"], 1)
            self.assertEqual(result["negative_control"]["validated_models"], 0)
            # Literal absence from registers does not prevent affine recovery.
            self.assertTrue(all(row["register"] == 0 for row in result["literal_presence"]))
            path.write_text("{}")
            with self.assertRaisesRegex(ValueError, "trace changed"): fit(config)

    def test_incomplete_traces_are_not_scored_as_protection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.json"
            for status, failures in (("step-limit", 0), ("completed", 1)):
                path.write_text(json.dumps({"status": status, "stack_read_failures": failures}))
                with self.assertRaisesRegex(ValueError, "incomplete"):
                    fit({"traces": [{"path": str(path), "sha256": file_hash(path)}], "targets": {}})

    def test_unexecuted_branch_targets_are_excluded_explicitly(self):
        with tempfile.TemporaryDirectory() as tmp:
            config={'traces':[],'targets':{'child':[None,3,8,29,None,101,105]}}
            for i,value in enumerate(config['targets']['child']):
                trace={'status':'completed','stack_read_failures':0,'samples':[
                    {'offset':4,'visit':0,'values':{'reg:x1':value if value is not None else 0}}]}
                path=Path(tmp)/f'{i}.json';path.write_text(json.dumps(trace))
                config['traces'].append({'path':str(path),'sha256':file_hash(path),'split':'training' if i<4 else 'heldout'})
            result=fit(config)['targets']['child']
            self.assertEqual(result['training_cases'],[1,2,3]);self.assertEqual(result['heldout_cases'],[5,6])
            self.assertEqual(result['unexecuted_cases'],[0,4]);self.assertIsNone(result['literal_presence'][0])
            self.assertEqual(result['recovery']['validated_models'],1)
            config['targets']['child'][2]=None
            with self.assertRaisesRegex(ValueError,'insufficient executed'):fit(config)
            # A layout that never reaches the calculation is neither a recovery
            # failure nor evidence of protection. Other targets are still scored.
            config['targets']['child']=[None]*7
            config['targets']['ordinary']=[3,8,29,101,105,107,109]
            result=fit(config)
            self.assertEqual(result['status'],'completed')
            self.assertNotIn('child',result['targets'])
            self.assertIn('ordinary',result['targets'])
            self.assertEqual(result['excluded_targets']['child'],{
                'reason':'not-executed-in-selected-layout',
                'unexecuted_cases':list(range(7))})

    def test_literal_and_return_recovery_without_an_odd_training_difference(self):
        targets=[2,6,10,14,3,99]
        with tempfile.TemporaryDirectory() as temp:
            config={"fit_protocol":"affine-literal-boundaries-v2","traces":[],"targets":{"reply":targets}}
            for i,value in enumerate(targets):
                trace={"status":"completed","stack_read_failures":0,"return_value":value,
                       "samples":[{"offset":4,"visit":0,"values":{"reg:x1":value,"reg:x2":value if i<4 else 0}}]}
                path=Path(temp)/f"{i}.json";path.write_text(json.dumps(trace))
                config["traces"].append({"path":str(path),"sha256":file_hash(path),"split":"training" if i<4 else "heldout"})
            current=fit(config)["targets"]["reply"]
            self.assertFalse(current["training_has_odd_difference"])
            self.assertTrue(current["negative_control_informative"])
            self.assertEqual(current["recovery"]["validated_models"],2)
            self.assertEqual(current["recovery"]["false_models"],1)
            self.assertEqual(current["by_scope"]["public-return"]["validated_locations"],1)
            self.assertEqual(current["negative_control"]["validated_models"],0)
            legacy=fit({**config,"fit_protocol":"affine-v1"})["targets"]["reply"]
            self.assertEqual(legacy["recovery"]["validated_models"],0)


if __name__ == "__main__":
    unittest.main()
