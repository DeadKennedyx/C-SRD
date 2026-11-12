"""Finite independent oracle checks include real member aliases and globals."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))
from record_observation_cases import cases,driver,expected,FUNCTIONS,LAYOUTS


class Oracles(unittest.TestCase):
    def test_compiled_records_match_independent_effects(self):
        compiler=shutil.which("clang") or shutil.which("cc")
        if not compiler:self.skipTest("C compiler unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for function in sorted(FUNCTIONS):
                union=function in ("records_union","records_mode")
                params=[{"kind":"record-buffer","read_only":False,"record":{"tag":"csrd_word" if union else "csrd_pair","union":union}},
                        {"kind":"uint32-buffer","read_only":False},{"kind":"uint32","read_only":False}]
                source=root/"driver.c";source.write_text(driver(function,params));binary=root/"run"
                run=subprocess.run([compiler,"-std=c11","-pedantic-errors","-Wall","-Wextra","-Werror","-O2",
                                ROOT/"tests/fixtures/records.c",source,"-o",binary],capture_output=True,text=True)
                self.assertEqual(run.returncode,0,run.stderr)
                for p,q in LAYOUTS:
                    for case in cases():
                        oracle=expected(function,case["memory"],p,q,case["x"])
                        wanted=[oracle["return_value"],*oracle["final_memory"],*oracle["persistent_state"]]
                        inputs=" ".join(map(str,[p,q,case["x"],*case["memory"]]))+"\n"
                        actual=list(map(int,subprocess.check_output([binary],input=inputs,text=True).split()))
                        self.assertEqual(actual,wanted,(function,p,q,case["x"]))


if __name__=="__main__":unittest.main()
