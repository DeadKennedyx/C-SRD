"""Guarded shared-memory effects, early returns and checked finite loop exits."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOL = str(Path(sys.argv.pop(1)).resolve())
ROOT = Path(__file__).resolve().parents[2]


class MemoryControl(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, *args, code=0):
        p = subprocess.run([TOOL, *map(str,args)], capture_output=True, text=True, timeout=90)
        self.assertEqual(p.returncode, code, p.stderr)

    def transform(self, source, *args):
        a,b,r = (self.root / name for name in ('a.c','b.c','r.json'))
        a.write_text('#include <stdint.h>\n'+source+'\n')
        self.invoke('transform', a, '-o', b, '--report', r, *args)
        return json.loads(r.read_text())['functions'][0]

    def compare(self, a, b, status='counterexample'):
        paths = [self.root/name for name in ('a.c','b.c')]
        for p,s in zip(paths,(a,b)): p.write_text('#include <stdint.h>\n'+s+'\n')
        r = self.root/'r.json'
        self.invoke('verify', *paths, '--report', r, code=0 if status=='proved-under-model' else 3)
        d = json.loads(r.read_text())['functions'][0]
        self.assertEqual(d['verification'],status,d)
        return d

    def test_fixture_transformations(self):
        for strategy in ('identity','affine'):
            for seed in (0,42,18446744073709551615):
                r=self.root/'r.json'
                self.invoke('transform', ROOT/'tests/fixtures/memory_control.c', '-o', self.root/'b.c',
                            '--strategy',strategy,'--seed',seed,'--report',r)
                rows=json.loads(r.read_text())['functions']
                self.assertEqual(len(rows),6)
                for f in rows:
                    self.assertEqual(f['status'],'transformed',f)
                    self.assertEqual(f['verification'],'proved-under-model',f)
                    self.assertEqual(f['semantic_model'],'guarded-memory-c11-v1')
                    if strategy=='affine':self.assertGreater(f['operations_without_decoding'],0)

    def test_conditional_stores_and_early_exit(self):
        head='uint32_t f(uint32_t*p,uint32_t*q,uint32_t x)'
        self.compare(head+'{if(x&1u)*p=x;return *q;}',head+'{*p=x;return *q;}')
        self.compare(head+'{if(x&1u)*p=x;return *q;}',head+'{if(x&2u)*p=x;return *q;}')
        self.compare(head+'{*q=*q;if(x&1u)*p=x;return 7u;}',head+'{*q=*q;if(x&1u)*q=x;return 7u;}')
        self.compare(head+'{if(x&1u){*p=x;return 7u;}*q=3u*x;return 11u;}',
                     head+'{if(x&1u){*p=x;}*q=3u*x;return 11u;}')
        self.compare(head+'{if(x&1u){*p=x;return 7u;}*q=x;return 7u;}',
                     head+'{if(x&1u){*p=x;}else{*q=x;}return 7u;}','proved-under-model')

    def test_loop_trip_count_store_order_and_carried_values(self):
        head='uint32_t f(uint32_t*p,uint32_t*q,uint32_t x)'
        a=head+'{uint32_t n=x&3u;for(uint32_t i=0u;i<n;++i){p[i]=*q+1u;}return *p;}'
        self.compare(a,head+'{uint32_t n=x&1u;for(uint32_t i=0u;i<n;++i){p[i]=*q+1u;}return *p;}')
        self.compare(a,head+'{uint32_t v=*q;uint32_t n=x&3u;for(uint32_t i=0u;i<n;++i){p[i]=v+1u;}return *p;}')
        self.compare(head+'{uint32_t s=x;for(uint32_t i=0u;i<3u;++i){s=s+1u;*p=s;}return *q;}',
                     head+'{*p=x+3u;return *q;}','proved-under-model')

    def test_zero_maximum_nested_and_stateful_cases(self):
        sources=(
            'uint32_t f(uint32_t*p,uint32_t x){for(uint32_t i=0u;i<0u;++i){p[i]=x;}return x+1u;}',
            'uint32_t f(uint32_t*p,uint32_t x){for(uint32_t i=0u;i<32u;++i){p[i]=x+3u;}return x;}',
            'uint32_t f(uint32_t*p,uint32_t x){for(uint32_t i=0u;i<2u;++i){for(uint32_t j=0u;j<2u;++j){p[i+j]=x;}}return p[0];}',
            'uint32_t g;uint32_t f(uint32_t*p,uint32_t x){if(x&1u){g=x+3u;return *p;}*p=g+5u;return g;}',
            'struct R{uint32_t a;uint32_t b;};uint32_t f(struct R*p,uint32_t x){if(x&1u){p->a=x+3u;}else{p->b=x+7u;}return p->a+p->b;}',
            'uint32_t f(unsigned char*p,uint32_t*q,uint32_t x){if(x&1u){p[0]=x+3u;}else{*q=x+7u;}return p[0]+*q;}',
        )
        for source in sources:
            with self.subTest(source=source):
                d=self.transform(source)
                self.assertEqual(d['verification'],'proved-under-model',d)

    def test_unsupported_loops_and_events_remain_unchanged(self):
        bodies=(
            'while(x){*p=x;x=x-1u;}return x;',
            'for(uint32_t i=0u;i<x;++i){*p=x;}return x;',
            'for(uint32_t i=0u;i<33u;++i){*p=x;}return x;',
            'uint32_t n=x&3u;for(uint32_t i=0u;i<n;++i){n=n+1u;*p=x;}return x;',
            'for(uint32_t i=0u;i<(*p&3u);++i){*p=x;}return x;',
            'for(uint32_t i=0u;i<3u;++i){i=i+1u;*p=x;}return x;',
            'for(uint32_t i=0u;i<3u;++i){if(x)break;*p=x;}return x;',
            'for(uint32_t i=0u;i<3u;++i){if(x)continue;*p=x;}return x;',
            'uint32_t v=1u;if(x){uint32_t v=3u;*p=v;}return v;',
        )
        for body in bodies:
            with self.subTest(body=body):
                d=self.transform('uint32_t f(uint32_t*p,uint32_t x){'+body+'}')
                self.assertEqual(d['status'],'unchanged',d)
                self.assertTrue(d['reason'])
                self.assertEqual((self.root/'a.c').read_bytes(),(self.root/'b.c').read_bytes())


if __name__=='__main__':unittest.main()
