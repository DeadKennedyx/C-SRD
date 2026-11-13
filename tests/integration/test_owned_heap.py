"""Owned allocation, failure, initialization and lifetime obligations."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOL = str(Path(sys.argv.pop(1)).resolve())
ROOT = Path(__file__).resolve().parents[2]
HEADER = '#include <stdint.h>\n#include <stdlib.h>\n'
HEAD = 'uint32_t f(uint32_t*out,uint32_t x)'


class OwnedHeap(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, *args, code=0):
        p = subprocess.run([TOOL, *map(str,args)], capture_output=True, text=True, timeout=90)
        self.assertEqual(p.returncode, code, p.stderr)

    def compare(self, a, b, status='counterexample'):
        paths = [self.root/name for name in ('a.c','b.c')]
        for path,source in zip(paths,(a,b)): path.write_text(HEADER+source+'\n')
        report = self.root/'r.json'
        self.invoke('verify', *paths, '--report', report, code=0 if status=='proved-under-model' else 3)
        result=json.loads(report.read_text())['functions'][0]
        self.assertEqual(result['verification'],status,result)
        return result

    def transform(self, source):
        a,b,r=(self.root/name for name in ('a.c','b.c','r.json'))
        a.write_text(HEADER+source+'\n')
        self.invoke('transform',a,'-o',b,'--report',r)
        return json.loads(r.read_text())['functions'][0], a, b

    def test_fixtures_and_determinism(self):
        for strategy in ('identity','affine'):
            for seed in (0,42,18446744073709551615):
                report=self.root/'r.json'
                output=self.root/'b.c'
                args=('transform',ROOT/'tests/fixtures/owned_heap.c','-o',output,
                      '--strategy',strategy,'--seed',seed,'--report',report)
                self.invoke(*args)
                previous=output.read_bytes()
                self.invoke(*args)
                self.assertEqual(output.read_bytes(),previous)
                rows=json.loads(report.read_text())['functions']
                self.assertEqual(len(rows),6)
                for row in rows:
                    self.assertEqual(row['verification'],'proved-under-model',row)
                    self.assertEqual(row['semantic_model'],'owned-heap-c11-v1')
                    self.assertTrue(row['owned_heap_handles'])

    def test_private_contents_may_differ_but_observables_must_match(self):
        prefix=HEAD+'{uint32_t*p=malloc(sizeof(uint32_t));if(!p)return x;'
        a=prefix+'*p=x+3u;uint32_t r=*p;free(p);*out=r;return r;}'
        b=prefix+'*p=x+10u;uint32_t r=*p-7u;free(p);*out=r;return r;}'
        self.compare(a,b,'proved-under-model')
        self.compare(a,b.replace('*p-7u','*p-8u'))
        self.compare(a,b.replace('*out=r','*out=r+1u'))
        self.compare(a,b.replace('if(!p)return x','if(!p)return x+1u'))
        self.compare(a,b.replace('sizeof(uint32_t)','2u*sizeof(uint32_t)'))

    def test_invalid_heap_operations_are_not_proved_even_against_themselves(self):
        bodies=(
            'uint32_t*p=malloc(4u);*p=x;uint32_t r=*p;free(p);return r;', # null
            'uint32_t*p=malloc(4u);if(!p)return x;uint32_t r=*p;free(p);return r;', # uninitialized
            'uint32_t*p=malloc(4u);if(!p)return x;p[1]=x;free(p);return x;', # bounds
            'uint32_t*p=malloc(4u);if(!p)return x;free(p);free(p);return x;',
            'uint32_t*p=malloc(4u);if(!p)return x;*p=x;free(p);return *p;',
            'uint32_t*p=malloc(4u);if(!p)return x;free(p);if(p)return x;return x;',
            'uint32_t*p=malloc(4u);if(!p)return x;return x;', # leaked successful allocation
            'uint32_t*p=malloc(8u);if(!p)return x;uint32_t*q=p+1u;free(q);return x;',
            'uint32_t*p=0;uint32_t*q=p+0u;free(q);return x;', # even null+0 is invalid
            'uint32_t*p=malloc(0u);if(!p)return x;*p=x;free(p);return x;',
            'uint32_t*p=malloc(4u);if(!p)return x;uint32_t*q=realloc(p,0u);free(q);return x;',
            'uint32_t*p=malloc(4u);if(!p)return x;*p=x;uint32_t*q=realloc(p,8u);'
            'if(!q){free(p);return x;}uint32_t r=q[1];free(q);return r;', # new tail
            'uint32_t*p=malloc(4u);if(!p)return x;uint32_t*alias=p;uint32_t*q=realloc(p,8u);'
            'if(!q){free(p);return x;}*alias=x;free(q);return x;', # stale alias
            'uint32_t*p=malloc(8u);if(!p)return x;p[1]=x;uint32_t*q=realloc(p,4u);'
            'if(!q){free(p);return x;}uint32_t r=q[1];free(q);return r;', # shrink
            'uint32_t*p=malloc(4u);if(!p)return x;p=realloc(p,8u);if(!p)return x;free(p);return x;', # failed resize leaks
        )
        for body in bodies:
            with self.subTest(body=body):
                source=HEAD+'{'+body+'}'
                self.compare(source,source)

    def test_allocator_traces_align_by_executed_order_across_branch_copies(self):
        shared=HEAD+'{uint32_t*p=malloc(4u);if(!p)return x;*p=x+3u;uint32_t r=*p;'
        shared+='if(x&1u){r=r+2u;}free(p);*out=r;return r;}'
        yes='uint32_t*p=malloc(4u);if(!p)return x;*p=x+5u;uint32_t r=*p;free(p);*out=r;return r;'
        no='uint32_t*q=malloc(4u);if(!q)return x;*q=x+3u;uint32_t s=*q;free(q);*out=s;return s;'
        split=HEAD+'{if(x&1u){'+yes+'}else{'+no+'}return 0u;}'
        self.compare(shared,split,'proved-under-model')
        self.compare(split,shared,'proved-under-model')
        self.compare(shared,split.replace('uint32_t*q=malloc(4u)','uint32_t*q=malloc(8u)'))
        self.compare(shared,split.replace('if(!q)return x','if(!q)return x+1u'))

        first='uint32_t*p=malloc(4u);if(!p)return x+1u;free(p);'
        second='uint32_t*q=malloc(8u);if(!q)return x+2u;free(q);return x+3u;'
        a=HEAD+'{if(x&1u){'+first+'}'+second+'}'
        b=HEAD+'{if(x&1u){'+first+second+'}else{'+second.replace('q','other')+'}return 0u;}'
        self.compare(a,b,'proved-under-model')
        self.compare(b,a,'proved-under-model')
        self.compare(a,b.replace('if(!q)return x+2u','if(!q)return x+4u',1))

        # Cleanup order and pre-event public memory remain observable even
        # when final memory and the return agree.
        prefix=HEAD+'{uint32_t*p=malloc(4u);if(!p)return x;uint32_t*q=malloc(4u);'
        prefix+='if(!q){free(p);return x;}*out=x;'
        self.compare(prefix+'free(p);free(q);return x;}',prefix+'free(q);free(p);return x;}')
        self.compare(prefix+'free(p);free(q);return x;}',
                     prefix+'*out=x+1u;free(p);*out=x;free(q);return x;}')

    def test_null_zero_size_one_past_and_guarded_positive_resize(self):
        bodies=(
            'free(0);return x+1u;',
            'uint32_t*p=malloc(0u);free(p);return x+1u;',
            'uint32_t*p=calloc(0u,4u);free(p);return x+1u;',
            'uint32_t*p=calloc(4u,2u);if(!p)return x;p[1]=p[0]+x;uint32_t r=p[1];free(p);return r;',
            'uint32_t*p=calloc(32u,4u);if(!p)return x;p[31]=p[0]+x;uint32_t r=p[31];free(p);return r;',
            'uint32_t*p=malloc(4u);if(!p)return x;uint32_t*q=p+1u;if(q){*p=x+1u;}uint32_t r=*p;free(p);return r;',
            'uint32_t n=x&3u;if(n==0u)return x;uint32_t*p=realloc(0,n*sizeof(uint32_t));if(!p)return x;*p=x+1u;uint32_t r=*p;free(p);return r;',
        )
        for body in bodies:
            with self.subTest(body=body):
                row,_,_=self.transform(HEAD+'{'+body+'}')
                self.assertEqual(row['verification'],'proved-under-model',row)

    def test_unsupported_constructs_preserve_source(self):
        bodies=(
            'uint32_t*p=malloc(x*sizeof(uint32_t));free(p);return x;',
            'uint32_t*p=malloc(33u*sizeof(uint32_t));free(p);return x;',
            'unsigned char*p=malloc(4u);free(p);return x;',
            'uint32_t*p=malloc(4u);uint32_t*q=malloc(4u);if(p==q)*out=x;free(p);free(q);return x;',
            'uint32_t*p=malloc(4u);free(out);free(p);return x;',
            'uint32_t*p=malloc(4u);if(p==NULL){return x;}free(p);return x;',
            'uint32_t*p=malloc(4u);*out=(uint32_t)(uintptr_t)p;free(p);return x;',
            'uint32_t*p=malloc(4u);for(uint32_t i=0u;i<3u*(p!=0);++i){*out=x;}free(p);return x;',
            'uint32_t*p=malloc(4u);free(p);(void)p;return x;',
        )
        for body in bodies:
            with self.subTest(body=body):
                row,a,b=self.transform(HEAD+'{'+body+'}')
                self.assertEqual(row['status'],'unchanged',row)
                self.assertTrue(row['reason'])
                self.assertEqual(a.read_bytes(),b.read_bytes())

    def test_failed_validation_does_not_publish_candidate(self):
        source=self.root/'unsafe.c'; output=self.root/'result.c'; report=self.root/'r.json'
        source.write_text(HEADER+HEAD+'{uint32_t*p=malloc(4u);if(!p)return x;uint32_t r=*p;free(p);return r;}\n')
        self.invoke('transform',source,'-o',output,'--report',report,code=1)
        self.assertFalse(output.exists())
        self.assertEqual(json.loads(report.read_text())['functions'][0]['verification'],'counterexample')

    def test_success_only_grading_is_explicit_and_unavailable_to_transform(self):
        source=HEAD+'{uint32_t*p=malloc(4u);if(!p)return x+1u;*p=x+3u;uint32_t r=*p;free(p);return r;}'
        plain=HEAD+'{return x+3u;}'
        self.compare(source,plain)
        a,b,r=(self.root/name for name in ('a.c','b.c','success.json'))
        self.invoke('verify',a,b,'--report',r,'--heap-observation','successful-private')
        report=json.loads(r.read_text());row=report['functions'][0]
        self.assertEqual(report['verification_heap_observation'],'successful-private')
        self.assertEqual(row['semantic_model'],'owned-heap-success-c11-v1')
        self.assertEqual(row['verification'],'proved-under-model')
        self.assertIn('failure behavior excluded',row['observations_checked'])
        b.write_text(HEADER+plain.replace('x+3u','x+4u')+'\n')
        self.invoke('verify',a,b,'--report',r,'--heap-observation','successful-private',code=3)
        self.assertEqual(json.loads(r.read_text())['functions'][0]['verification'],'counterexample')
        self.invoke('transform',a,'-o',self.root/'out.c','--heap-observation','successful-private',code=2)
        self.assertFalse((self.root/'out.c').exists())


if __name__=='__main__': unittest.main()
