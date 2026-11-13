"""Independent finite stream oracle checked against real C library execution."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import stdio_observation_cases as io
from grade_byte_reconstruction import batch_driver

PARAMETERS=[{'kind':kind,'read_only':False} for kind in ('file-stream','file-stream','uint32-buffer','uint32')]


def compilers():
    candidates=[shutil.which('clang') or next((shutil.which('clang-'+str(v)) for v in range(30,13,-1) if shutil.which('clang-'+str(v))),None),shutil.which('gcc')]
    return [c for c in candidates if c]


class StdioOracles(unittest.TestCase):
    def test_protocol_partitions_and_eof_paths(self):
        vectors=io.cases();self.assertEqual(len(vectors),24)
        self.assertEqual([v['split'] for v in vectors],['training']*12+['heldout']*12)
        for fn in io.FUNCTIONS:
            for p,q in io.LAYOUTS:
                for case in vectors:
                    result=io.expected(fn,case['memory'],p,q,case['x'])
                    self.assertEqual(len(result['stdio_state']),139)
                    self.assertEqual(result['targets']['public_return'],result['return_value'])
                    self.assertTrue(all(len(e)==68 for e in result['stdio_events']))
                    self.assertEqual(result['final_memory'][:p],case['memory'][:p])
                    self.assertEqual(result['final_memory'][p+1:],case['memory'][p+1:])
                    if fn=='io_read_mix' and q:self.assertIsNone(result['targets']['sum'])
        with self.assertRaises(ValueError):io.cases('unimplemented')
        with self.assertRaises(ValueError):io.signature('io_status',PARAMETERS[:-1])

    @unittest.skipUnless(sys.platform.startswith('linux'),'real-stream observer protocol currently Linux/glibc')
    def test_real_streams_match_independent_oracle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            if not compilers():self.skipTest('C compiler unavailable')
            for compiler in compilers():
                for fn in sorted(io.FUNCTIONS):
                    harness=root/'driver.c';binary=root/'run'
                    harness.write_text(batch_driver(fn,PARAMETERS,'stdio'))
                    subprocess.run([compiler,'-std=c11','-pedantic-errors','-Wall','-Wextra','-Werror','-O2',
                                    harness,ROOT/'tests/fixtures/stdio_calls.c','-o',binary],check=True,capture_output=True)
                    inputs=[];wanted=[]
                    for p,q in io.LAYOUTS:
                        for case in io.cases():
                            result=io.expected(fn,case['memory'],p,q,case['x'])
                            inputs.append(' '.join(map(str,[p,q,case['x'],*case['memory']])))
                            wanted.extend([result['return_value'],*result['final_memory'],*result['stdio_state']])
                    process=subprocess.run([binary],input='\n'.join(inputs)+'\n',capture_output=True,text=True,check=True)
                    self.assertEqual(list(map(int,process.stdout.split())),wanted,(compiler,fn))

    @unittest.skipUnless(sys.platform.startswith('linux'),'throughput harness uses Linux resource accounting')
    def test_cost_harness_executes_defined_stream_sequences(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            if not compilers():self.skipTest('C compiler unavailable')
            for fn in sorted(io.FUNCTIONS):
                harness=root/'driver.c';binary=root/'run';harness.write_text(io.cost_driver(fn,PARAMETERS))
                subprocess.run([compilers()[0],'-std=c11','-pedantic-errors','-Wall','-Wextra','-Werror','-O2',
                                harness,ROOT/'tests/fixtures/stdio_calls.c','-o',binary],check=True,capture_output=True)
                process=subprocess.run([binary,'128','42'],check=True,text=True,capture_output=True)
                wall,cpu,rss,checksum=process.stdout.split()
                self.assertGreater(float(wall),0);self.assertGreater(float(cpu),0)
                self.assertGreater(int(rss),0);self.assertGreaterEqual(int(checksum),0)


if __name__=='__main__':unittest.main()
