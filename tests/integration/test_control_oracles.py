"""Compiled branch/loop effects against separately written Python oracles."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from control_observation_cases import cases,expected,FUNCTIONS,LAYOUTS
from grade_byte_reconstruction import batch_driver


class ControlOracles(unittest.TestCase):
    def test_compiled_functions_and_branch_inputs(self):
        compiler=shutil.which('clang') or shutil.which('cc')
        if not compiler:self.skipTest('C compiler unavailable')
        vectors=cases()
        training=[v for v in vectors if v['split']=='training']
        self.assertEqual({v['x']&3 for v in training},{0,1,2,3})
        self.assertEqual({(v['x']>>1)&3 for v in training},{0,1,2,3})
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for function in sorted(FUNCTIONS):
                params=[{'kind':'uint32-buffer','read_only':False},{'kind':'uint32-buffer','read_only':False},{'kind':'uint32','read_only':False}]
                source=root/'driver.c';source.write_text(batch_driver(function,params,'control'));binary=root/'run'
                p=subprocess.run([compiler,'-std=c11','-pedantic-errors','-Wall','-Wextra','-Werror','-O2',
                                  ROOT/'tests/fixtures/memory_control.c',source,'-o',binary],capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stderr)
                inputs=[];wanted=[]
                for a,b in LAYOUTS:
                    for v in vectors:
                        result=expected(function,v['memory'],a,b,v['x'])
                        wanted.extend([result['return_value'],*result['final_memory']])
                        inputs.append(' '.join(map(str,[a,b,v['x'],*v['memory']])))
                actual=subprocess.check_output([binary],input='\n'.join(inputs)+'\n',text=True)
                self.assertEqual(list(map(int,actual.split())),wanted,function)


if __name__=='__main__':unittest.main()
