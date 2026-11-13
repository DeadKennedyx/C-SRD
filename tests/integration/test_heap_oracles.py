"""Check independent heap oracles against compiled C and controlled allocators."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from heap_observation_cases import FUNCTIONS,LAYOUTS,cases,expected,signature,driver
from fit_buffer_traces import run as fit,location_scope
from audit_protection import file_hash


class HeapOracles(unittest.TestCase):
    def test_compiled_failure_and_move_outcomes(self):
        compiler=shutil.which('clang-18') or shutil.which('clang') or shutil.which('gcc')
        if not compiler:self.skipTest('C compiler unavailable')
        names=sorted(FUNCTIONS)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);obj=root/'input.o';exe=root/'run';driver=root/'driver.c'
            flags=['-std=c11','-Wall','-Wextra','-Werror','-pedantic-errors','-O2']
            subprocess.run([compiler,*flags,*[f'-D{name}=original_{name}' for name in (*names,'malloc','calloc','realloc','free')],
                            '-c',str(ROOT/'tests/fixtures/owned_heap.c'),'-o',str(obj)],check=True,capture_output=True)
            declarations='\n'.join('uint32_t original_'+name+'(uint32_t*,uint32_t);' for name in names)
            body=(ROOT/'tests/differential/heap_allocator.c').read_text()+declarations+'\n'+r'''
int main(void){
 uint32_t memory[64],x;unsigned mask,move,fn,p;
 uint32_t (*functions[])(uint32_t*,uint32_t)={'''+','.join('original_'+name for name in names)+r'''};
 while(scanf("%u %u %u %u %u",&fn,&mask,&move,&p,&x)==5){
  if(fn>=6 || p>=64)return 2;
  for(unsigned i=0;i<64;i++)if(scanf("%u",&memory[i])!=1)return 3;
  heap_reset(mask,move);uint32_t result=functions[fn](memory+p,x);
  heap_reset(mask,move);printf("%u",result);
  for(unsigned i=0;i<64;i++)printf(" %u",memory[i]);puts("");
 }return 0;
}
'''
            driver.write_text(body)
            subprocess.run([compiler,*flags,str(driver),str(obj),'-o',str(exe)],check=True,capture_output=True)
            inputs=[];wanted=[]
            for fi,name in enumerate(names):
                for case in cases():
                    for p,q in LAYOUTS:
                        for mask in range(8):
                            for move in (0,1):
                                inputs.append(' '.join(map(str,[fi,mask,move,p,case['x'],*case['memory']])))
                                oracle=expected(name,case['memory'],p,q,case['x'],failures=mask)
                                wanted.append([oracle['return_value'],*oracle['final_memory']])
            run=subprocess.run([exe],input='\n'.join(inputs)+'\n',capture_output=True,text=True,check=True,timeout=30)
            actual=[list(map(int,line.split())) for line in run.stdout.splitlines()]
            self.assertEqual(actual,wanted)
            self.assertEqual(len(actual),3072)

    def test_heap_locations_fit_and_incomplete_sampling_is_rejected(self):
        self.assertEqual(location_scope('0:0:heap:0:1'),'heap-memory')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);entries=[]
            labels=[0,1,2,4,9,17]
            for i,value in enumerate(labels):
                path=root/f'{i}.json'
                path.write_text(json.dumps({'status':'completed','stack_read_failures':0,'heap_observer_errors':[],
                    'samples':[{'offset':4,'visit':0,'values':{'heap:0:0':(3*value+7)&0xffffffff}}]}))
                entries.append({'path':str(path),'sha256':file_hash(path),'split':'training' if i<3 else 'heldout'})
            result=fit({'traces':entries,'targets':{'value':labels}})
            target=result['targets']['value']
            self.assertGreater(target['by_scope']['heap-memory']['validated_locations'],0)
            bad=json.loads(path.read_text());bad['heap_observer_errors']=['read failed'];path.write_text(json.dumps(bad))
            entries[-1]['sha256']=file_hash(path)
            with self.assertRaisesRegex(ValueError,'incomplete'):fit({'traces':entries,'targets':{'value':labels}})

    def test_public_signature_validation(self):
        self.assertIn('heap_pair',signature('heap_pair',[{'kind':'uint32-buffer'},{'kind':'uint32'}])[1])
        with self.assertRaises(ValueError):signature('unknown',[])

    @unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('gdb'),'Linux GDB unavailable')
    def test_allocator_abi_tracker_does_not_double_count_tail_calls(self):
        from inspect_region_binaries import elf_functions
        compiler=shutil.which('gcc') or shutil.which('clang-18')
        if not compiler:self.skipTest('C compiler unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);library=root/'fixture.so';harness=root/'driver.c';binary=root/'run'
            subprocess.run([compiler,'-std=c11','-O0','-fPIC','-shared',str(ROOT/'tests/fixtures/owned_heap.c'),'-o',str(library)],
                           check=True,capture_output=True)
            fn='heap_nullable';harness.write_text(driver(fn,[{'kind':'uint32-buffer'},{'kind':'uint32'}]))
            subprocess.run([compiler,'-std=c11','-O2',str(harness),str(library),'-o',str(binary)],check=True,capture_output=True)
            inputs=root/'input';inputs.write_text(' '.join(map(str,[4,0,9,*range(64)]))+'\n')
            config=root/'config.json';tracepath=root/'trace.json'
            config.write_text(json.dumps({'function':fn,'function_bytes':elf_functions(library.read_bytes(),[fn])[fn]['bytes'],
                'step_limit':256,'call_scope':True,'observe_call_events':False,'observe_heap':True,
                'input_file':str(inputs),'output':str(tracepath)}))
            script=root/'run.gdb';script.write_text('python\nimport sys\nsys.path.insert(0,'+repr(str(ROOT/'tools'))+
                ')\nimport gdb_buffer_trace\ngdb_buffer_trace.main('+repr(str(config))+')\nend\n')
            subprocess.run(['gdb','--nx','--batch','-iex','set auto-load off','-x',str(script),'--args',str(binary)],
                           capture_output=True,text=True,check=True,timeout=30)
            trace=json.loads(tracepath.read_text())
            if 'Operation not permitted' in trace.get('error',''):self.skipTest('ptrace unavailable')
            self.assertEqual(trace['status'],'completed',trace.get('error'))
            self.assertEqual(trace['heap_observer_errors'],[])
            self.assertEqual(trace['heap_live_objects_at_return'],0)
            self.assertEqual(len(trace['heap_events']),2)
            self.assertEqual(trace['heap_events'][-1]['kind'],'free')
            self.assertTrue(any(k.startswith('heap:') for s in trace['samples'] for k in s['values']))
            oracle=expected(fn,list(range(64)),4,0,9)
            for key in ('return_value','final_memory'):self.assertEqual(trace[key],oracle[key])


if __name__=='__main__':unittest.main()
