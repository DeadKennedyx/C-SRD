"""Independent finite oracle checks for recursion and indirect stateful calls."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from dispatch_observation_cases import cases,driver,expected,FUNCTIONS,LAYOUTS,parameters


class Oracles(unittest.TestCase):
    def test_compiled_environment_matches_independent_effects(self):
        compiler=shutil.which('clang') or shutil.which('cc')
        if not compiler:self.skipTest('C compiler unavailable')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for function in sorted(FUNCTIONS):
                source=root/'driver.c';source.write_text(driver(function,parameters(function)));binary=root/'run'
                subprocess.run([compiler,'-std=c11','-pedantic-errors','-Wall','-Wextra','-Werror','-O2',
                                ROOT/'tests/fixtures/guarded_calls.c',source,'-o',binary],capture_output=True,check=True)
                for p,q in LAYOUTS:
                    for case in cases():
                        oracle=expected(function,case['memory'],p,q,case['x'])
                        wanted=[oracle['return_value'],*oracle['final_memory'],oracle['external_state'],len(oracle['events'])]
                        wanted += [v for event in oracle['events'] for v in event]
                        inputs=' '.join(map(str,[p,q,case['x'],*case['memory']]))+'\n'
                        actual=list(map(int,subprocess.check_output([binary],input=inputs,text=True).split()))
                        self.assertEqual(actual,wanted,(function,p,q,case['x']))


if __name__=='__main__':unittest.main()
