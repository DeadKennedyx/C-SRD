"""Executed call traces, callback identities and inductive recursion contracts."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOL=str(Path(sys.argv.pop(1)).resolve())
ROOT=Path(__file__).resolve().parents[2]
HEADER='''#include <stdint.h>
typedef uint32_t(*operation)(uint32_t*,uint32_t*,uint32_t);
uint32_t effect_value(uint32_t);void effect_note(uint32_t);
uint32_t effect_mix(uint32_t*,uint32_t*,uint32_t);
'''
HEAD='uint32_t f(uint32_t*p,uint32_t*q,uint32_t x)'
CALLBACK='uint32_t f(uint32_t*p,uint32_t*q,uint32_t x,operation first,operation second)'


class GuardedCalls(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.contracts=self.root/'contracts.json'
        base=json.loads((ROOT/'tests/fixtures/calls.json').read_text())
        base['model']='opaque-guarded-v2'
        params=[{'kind':'uint32-buffer','read_only':False,'minimum_elements':1}]*2+[{'kind':'uint32'}]
        base['functions'].append({'name':'f','returns':'uint32','parameters':params,
                                 'recursion':{'rank_parameter':2,'maximum_rank':8}})
        for name in ('first','second'):
            base['functions'].append({'name':'f','indirect_parameter':name,'returns':'uint32','parameters':params})
        self.contracts.write_text(json.dumps(base))

    def tearDown(self):self.temp.cleanup()

    def invoke(self,*args,code=0):
        p=subprocess.run([TOOL,*map(str,args)],capture_output=True,text=True,timeout=90)
        self.assertEqual(p.returncode,code,p.stderr)
        return p

    def compare(self,a,b,status='counterexample',mode='events'):
        files=[self.root/name for name in ('a.c','b.c')]
        for p,text in zip(files,(a,b)):p.write_text(HEADER+text+'\n')
        report=self.root/'report.json'
        self.invoke('verify',*files,'--function','f','--call-contracts',self.contracts,'--report',report,
                    '--recursion-observation',mode,
                    code=0 if status=='proved-under-model' else 3)
        row=json.loads(report.read_text())['functions'][0]
        self.assertEqual(row['verification'],status,row)
        return row

    def transform(self,source,code=0):
        a,b,r=[self.root/name for name in ('a.c','output.c','report.json')]
        a.write_text(HEADER+source+'\n')
        if b.exists():b.unlink()
        self.invoke('transform',a,'-o',b,'--call-contracts',self.contracts,'--report',r,code=code)
        return json.loads(r.read_text())['functions'][0],a,b

    def test_fixtures_and_determinism(self):
        for strategy in ('identity','affine'):
            for seed in (0,42,18446744073709551615):
                output=self.root/'candidate.c';report=self.root/'report.json'
                args=('transform',ROOT/'tests/fixtures/guarded_calls.c','-o',output,'--call-contracts',
                      ROOT/'tests/fixtures/guarded_calls.json','--strategy',strategy,'--seed',seed,'--report',report)
                self.invoke(*args);previous=output.read_bytes();self.invoke(*args)
                self.assertEqual(previous,output.read_bytes())
                rows=json.loads(report.read_text())['functions'];self.assertEqual(len(rows),6)
                for row in rows:
                    self.assertEqual(row['status'],'transformed',row)
                    self.assertEqual(row['verification'],'proved-under-model',row)
                    self.assertEqual(row['semantic_model'],'guarded-calls-c11-v2')
                    self.assertTrue(row['ordered_calls'])
                recursive=[r for r in rows if 'recursion' in r];self.assertEqual(len(recursive),2)
                self.assertTrue(all(r['recursion']['maximum_activation_depth']==9 for r in recursive))

    def test_executed_order_not_static_branch_positions(self):
        a=HEAD+'{if(x&1u){effect_note(x);}uint32_t v=effect_value(x+3u);*p=v;return v;}'
        b=HEAD+'{if(x&1u){effect_note(x);uint32_t v=effect_value(x+3u);*p=v;return v;}'
        b+='else{uint32_t w=effect_value(x+3u);*p=w;return w;}return 0u;}'
        self.compare(a,b,'proved-under-model');self.compare(b,a,'proved-under-model')
        self.compare(a,b.replace('effect_note(x)','effect_note(x+1u)'))
        self.compare(a,b.replace('else{','else{effect_note(x);'))

    def test_guarded_assignments_loops_and_call_havoc(self):
        a=HEAD+'{uint32_t r=x;if(x&1u){r=effect_value(x);}return r;}'
        b=HEAD+'{if(x&1u){uint32_t y=effect_value(x);return y;}return x;}'
        self.compare(a,b,'proved-under-model')
        self.compare(a,b.replace('return x;','return x+1u;'))
        a=HEAD+'{uint32_t n=x&3u;for(uint32_t i=0u;i<n;++i){effect_note(i+x);}return *p;}'
        row,_,_=self.transform(a);self.assertEqual(row['verification'],'proved-under-model',row)
        self.compare(a,a.replace('x&3u','(x&3u)+1u'))
        a=HEAD+'{uint32_t before=*p;if(x&1u){effect_mix(p,q,x);}return before+*p;}'
        self.compare(a,a.replace('before+*p','before+before'))

    def test_indirect_target_identity_and_memory_are_observed(self):
        a=CALLBACK+'{uint32_t v=first(p,q,x);return v;}'
        row=self.compare(a,a.replace('first(p,q,x)','second(p,q,x)'))
        targets=row['proof']['local_countermodel']
        self.assertNotEqual(targets['function_target:first'],targets['function_target:second'])
        self.compare(a,a.replace('first(p,q,x)','first(q,p,x)'))
        a=CALLBACK+'{uint32_t before=*p;uint32_t v=first(p,q,x);return v+*p+before;}'
        self.compare(a,a.replace('v+*p+before','v+before+before'))
        self.compare(a,a,'proved-under-model')

    def test_recursion_rank_checked_even_against_the_same_source(self):
        for body in (
            'if(x>8u)return *p;if(x==0u)return *q;return f(p,q,x);',
            'if(x>8u)return *p;if(x==0u)return *q;return f(p,q,x+1u);',
            'if(x>8u)return *p;return f(p,q,x-1u);',
            'if(x>16u)return *p;if(x==0u)return *q;return f(p,q,x-1u);',
            'x=x+1u;if(x>8u)return *p;return f(p,q,x-1u);',
        ):
            with self.subTest(body=body):self.compare(HEAD+'{'+body+'}',HEAD+'{'+body+'}')
        valid=HEAD+'{if(x>8u)return *p;if(x==0u)return *q;uint32_t y=f(p,q,x-1u);return y+x;}'
        self.compare(valid,valid,'proved-under-model')
        self.compare(valid,valid.replace('return *q','return *q+1u'))
        row,_,output=self.transform(HEAD+'{if(x>8u)return *p;return f(p,q,x);}',code=1)
        self.assertEqual(row['verification'],'counterexample');self.assertFalse(output.exists())

    def test_recursive_buffer_contract_must_cover_its_body(self):
        row,a,b=self.transform(HEAD+'{if(x>8u)return p[1];if(x==0u)return *q;return f(p,q,x-1u);}')
        self.assertEqual(row['status'],'unchanged');self.assertIn('footprint',row['reason'])
        self.assertEqual(a.read_bytes(),b.read_bytes())

    def test_bounded_body_comparison_admits_inlining_with_aliases(self):
        prefix=HEAD+'{if(x>1u)return *p;if(x==0u)return *q+1u;uint32_t before=*p;*p=before+3u;'
        a=prefix+'uint32_t child=f(p,q,x-1u);*q=child+5u;return child+before;}'
        b=prefix+'uint32_t child=*q+1u;*q=child+5u;return child+before;}'
        self.compare(a,b)
        row=self.compare(a,b,'proved-under-model',mode='bounded-body')
        self.assertEqual(row['semantic_model'],'bounded-recursion-body-c11-v1')
        self.compare(b,a,'proved-under-model',mode='bounded-body')
        self.compare(a,b.replace('*q=child+5u','*q=child+6u'),mode='bounded-body')
        self.compare(a,b.replace('return child+before','return child+before+1u'),mode='bounded-body')

    def test_expansion_preserves_external_event_order_and_private_frames(self):
        prefix=HEAD+'{uint32_t r=effect_value(x);if(x>1u)return r;if(x==0u)return r;'
        a=prefix+'uint32_t child=f(p,q,0u);return child+r;}'
        b=prefix+'uint32_t child=effect_value(0u);return child+r;}'
        self.compare(a,b,'proved-under-model',mode='bounded-body')
        self.compare(a,b.replace('effect_value(0u)','effect_value(1u)'),mode='bounded-body')
        self.compare(a,b.replace('return child+r','return child+child'),mode='bounded-body')

    def test_expansion_never_silently_truncates_invalid_recursion(self):
        for body in ('return f(p,q,x);','if(x==0u)return *p;return f(p,q,x-1u);',
                     'if(x>8u)return *p;return f(p,q,x-1u);'):
            source=HEAD+'{'+body+'}'
            self.compare(source,source,mode='bounded-body')
        a=self.root/'a.c';a.write_text(HEADER+HEAD+'{return x;}')
        self.invoke('transform',a,'-o',self.root/'out.c','--recursion-observation','bounded-body',code=2)

    def test_induction_and_body_expansion_have_distinct_limits(self):
        spec=json.loads(self.contracts.read_text())
        next(f for f in spec['functions'] if f.get('recursion'))['recursion']['maximum_rank']=16
        self.contracts.write_text(json.dumps(spec))
        source=HEAD+'{if(x>16u)return *p;if(x==0u)return *q;return f(p,q,x-1u);}'
        self.compare(source,source,'proved-under-model')
        row=self.compare(source,source,'unsupported',mode='bounded-body')
        self.assertIn('maximum_rank <= 8',row['proof']['reason'])

    def test_calling_another_ranked_function_is_an_opaque_boundary(self):
        source=HEAD+';uint32_t g(uint32_t*p,uint32_t*q,uint32_t x){return f(p,q,x);}'
        row,_,_=self.transform(source)
        self.assertEqual(row['verification'],'proved-under-model',row)
        self.assertFalse(row['ordered_calls'][0]['recursive']);self.assertNotIn('recursion',row)

    def test_unsupported_callbacks_preserve_the_source(self):
        for source in (
            CALLBACK+'{return first(p,q,second(p,q,x));}',
            CALLBACK+'{operation local=first;return local(p,q,x);}',
            CALLBACK+'{if(first==0)return x;return first(p,q,x);}',
            CALLBACK+'{first=second;return first(p,q,x);}',
            CALLBACK+'{uint32_t r=first(p,q,x);return second(p,q,r)+1u;}',
            'uint32_t f(uint32_t x,uint32_t(*unknown)(uint32_t)){return unknown(x);}',
        ):
            with self.subTest(source=source):
                row,a,b=self.transform(source);self.assertEqual(row['status'],'unchanged',row)
                self.assertTrue(row['reason']);self.assertEqual(a.read_bytes(),b.read_bytes())

    def test_invalid_contracts_are_rejected(self):
        source=self.root/'a.c';source.write_text(HEADER+HEAD+'{return x;}\n')
        valid=json.loads(self.contracts.read_text())
        for mutation in ('negative_rank','wrong_type','too_large','indirect_recursion','old_model'):
            spec=json.loads(json.dumps(valid));recursive=next(f for f in spec['functions'] if f.get('recursion'))
            if mutation=='negative_rank':recursive['recursion']['rank_parameter']=-1
            elif mutation=='wrong_type':recursive['recursion']['rank_parameter']=0
            elif mutation=='too_large':recursive['recursion']['maximum_rank']=33
            elif mutation=='indirect_recursion':recursive['indirect_parameter']='first'
            else:spec['model']='opaque-sequenced-v1'
            self.contracts.write_text(json.dumps(spec))
            with self.subTest(mutation=mutation):self.invoke('analyze',source,'--call-contracts',self.contracts,code=2)


if __name__=='__main__':unittest.main()
