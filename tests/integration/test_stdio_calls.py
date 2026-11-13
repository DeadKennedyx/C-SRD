"""Ordered stream identity/effects and defined signed-to-unsigned boundaries."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOL = str(Path(sys.argv.pop(1)).resolve())
ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT/'tests/fixtures/stdio_calls.json'
HEADER = '#include <stdint.h>\n#include <stdio.h>\n'
HEAD = 'uint32_t f(FILE*input,FILE*output,uint32_t*p,uint32_t x)'


class StreamCalls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)

    def tearDown(self): self.temp.cleanup()

    def invoke(self, *args, code=0):
        result = subprocess.run([TOOL, *map(str,args)], capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, code, result.stderr)
        return result

    def compare(self, a, b, status='counterexample'):
        source, candidate, report = [self.root/n for n in ('a.c','b.c','proof.json')]
        source.write_text(HEADER+HEAD+a+'\n'); candidate.write_text(HEADER+HEAD+b+'\n')
        self.invoke('verify', source, candidate, '--function','f', '--call-contracts',CONTRACTS,
                    '--report', report, code=0 if status=='proved-under-model' else 3)
        row = json.loads(report.read_text())['functions'][0]
        self.assertEqual(row['verification'],status,row)
        return row

    def transform(self, body, code=0):
        source, candidate, report = [self.root/n for n in ('a.c','out.c','report.json')]
        source.write_text(HEADER+HEAD+body+'\n')
        if candidate.exists(): candidate.unlink()
        self.invoke('transform',source,'-o',candidate,'--call-contracts',CONTRACTS,'--report',report,code=code)
        return json.loads(report.read_text())['functions'][0], source, candidate

    def test_fixtures_are_transformed_and_deterministic(self):
        for strategy in ('identity','affine'):
            for seed in (0,42,18446744073709551615):
                candidate, report = self.root/'out.c', self.root/'report.json'
                args = ('transform',ROOT/'tests/fixtures/stdio_calls.c','-o',candidate,'--call-contracts',CONTRACTS,
                        '--strategy',strategy,'--seed',seed,'--report',report)
                self.invoke(*args); previous = candidate.read_bytes(); self.invoke(*args)
                self.assertEqual(candidate.read_bytes(),previous)
                rows = json.loads(report.read_text())['functions']; self.assertEqual(len(rows),6)
                for row in rows:
                    self.assertEqual(row['status'],'transformed',row)
                    self.assertEqual(row['verification'],'proved-under-model',row)
                    self.assertEqual(row['semantic_model'],'ordered-stdio-c11-v1')
                    self.assertEqual(row['call_contract_model'],'opaque-stdio-v3')

    def test_compiler_frozen_input_keeps_standard_header_provenance(self):
        compiler=shutil.which('clang') or next((shutil.which('clang-'+str(v)) for v in range(30,13,-1) if shutil.which('clang-'+str(v))),None)
        if not compiler:self.skipTest('Clang preprocessor unavailable')
        source=self.root/'a.c';frozen=self.root/'frozen.i';report=self.root/'proof.json'
        source.write_text(HEADER+HEAD+'{(void)output;uint32_t c=(uint32_t)fgetc(input);*p=c+x;'+('\n'*16)+'return *p;}\n')
        subprocess.run([compiler,'-std=c11','-O2','-E',source,'-o',frozen],capture_output=True,check=True)
        self.invoke('verify',source,frozen,'--function','f','--call-contracts',CONTRACTS,'--report',report)
        self.assertEqual(json.loads(report.read_text())['functions'][0]['verification'],'proved-under-model')

    def test_signed_statuses_preserved_including_eof_and_errors(self):
        a = '{uint32_t c=(uint32_t)fgetc(input);if(c>255u){uint32_t e=(uint32_t)ferror(input);return e+101u;}return c+x;}'
        self.compare(a,a,'proved-under-model')
        self.compare(a,a.replace('return e+101u','return 101u'))
        self.compare(a,a.replace('c>255u','c>256u'))
        self.compare(a,a.replace('return c+x','return (c&255u)+x'),'proved-under-model')

    def test_character_arguments_and_event_order_are_observed(self):
        a = '{uint32_t y=(uint32_t)fputc((int)(x&255u),output);uint32_t z=(uint32_t)fflush(output);return y+z;}'
        self.compare(a,a.replace('x&255u','(x+1u)&255u'))
        self.compare(a,'{uint32_t z=(uint32_t)fflush(output);uint32_t y=(uint32_t)fputc((int)(x&255u),output);return y+z;}')
        self.compare(a,a.replace('uint32_t z=(uint32_t)fflush(output);','uint32_t z=0u;'))

    def test_stream_identity_is_observed_including_possible_aliases(self):
        a = '{return (uint32_t)fputc((int)(x&255u),output);}'
        row = self.compare(a,a.replace(',output',',input'))
        ids = row['proof']['local_countermodel']
        self.assertNotEqual(ids['stream_target:input'],ids['stream_target:output'])
        self.compare(a,a,'proved-under-model')

    def test_clear_error_state_operation_cannot_be_removed_or_reordered(self):
        a = '{uint32_t e=(uint32_t)ferror(input);clearerr(input);uint32_t after=(uint32_t)feof(input);return e+after+x;}'
        self.compare(a,a.replace('clearerr(input);',''))
        self.compare(a,a.replace('clearerr(input);','').replace('return e','clearerr(input);return e'))

    def test_static_site_fast_proof_falls_back_to_executed_event_semantics(self):
        a = '{if(x&1u){clearerr(input);}else{clearerr(output);}uint32_t e=(uint32_t)ferror(input);return e;}'
        b = '{if((x&1u)==0u){clearerr(output);}else{clearerr(input);}uint32_t e=(uint32_t)ferror(input);return e;}'
        row = self.compare(a,b,'proved-under-model')
        self.assertTrue(row['proof']['prior_attempts'])
        b = '{if(x&1u){clearerr(input);uint32_t e=(uint32_t)ferror(input);return e;}'
        b += 'else{clearerr(output);uint32_t other=(uint32_t)ferror(input);return other;}return 0u;}'
        self.compare(a,b,'proved-under-model')

    def test_disjoint_stream_storage_cannot_mutate_user_buffers(self):
        a = '{uint32_t before=*p;uint32_t c=(uint32_t)fgetc(input);return before+*p+c;}'
        self.compare(a,a.replace('before+*p+c','2u*before+c'),'proved-under-model')

    def test_int_character_range_is_proved_before_emission(self):
        row,_,candidate = self.transform('{return (uint32_t)fputc((int)x,output);}',code=1)
        self.assertEqual(row['verification'],'counterexample'); self.assertFalse(candidate.exists())
        row,_,_ = self.transform('{return (uint32_t)fputc((int)(x&2147483647u),output);}')
        self.assertEqual(row['verification'],'proved-under-model',row)
        row,_,_ = self.transform('{uint32_t y=(uint32_t)fputc(255,output);return y+x;}')
        self.assertEqual(row['verification'],'proved-under-model',row)

    def test_unsupported_stream_operations_are_unchanged(self):
        for body in (
            '{FILE*copy=input;return (uint32_t)fgetc(copy);}',
            '{return (uint32_t)fflush(0);}',
            '{if(input==output)return x;return (uint32_t)fgetc(input);}',
            '{return (uint32_t)fgetc(input+1);}',
            '{return (uint32_t)fgetc(input)+x;}',
            '{uint32_t c=fgetc(input);return c;}',
            '{return (uint32_t)fputc(-1,output);}',
            '{return (uint32_t)fclose(output);}',
            '{return (uint32_t)fprintf(output,"%u",x);}',
        ):
            with self.subTest(body=body):
                row,source,candidate = self.transform(body)
                self.assertEqual(row['status'],'unchanged',row)
                self.assertTrue(row['reason']); self.assertEqual(source.read_bytes(),candidate.read_bytes())

    def test_macro_call_is_not_rewritten(self):
        source, candidate, report = self.root/'a.c',self.root/'out.c',self.root/'report.json'
        source.write_text(HEADER+'#define READ(s) fgetc(s)\n'+HEAD+'{return (uint32_t)READ(input);}\n')
        self.invoke('transform',source,'-o',candidate,'--call-contracts',CONTRACTS,'--report',report)
        self.assertEqual(json.loads(report.read_text())['functions'][0]['status'],'unchanged')
        self.assertEqual(source.read_bytes(),candidate.read_bytes())

    def test_contract_interface_is_exact(self):
        source=self.root/'a.c';source.write_text(HEADER+HEAD+'{return x;}\n')
        for name,kind in [('fgetc','uint32'),('fprintf','int32')]:
            data=json.loads(CONTRACTS.read_text());data['functions'][0].update(name=name,returns=kind)
            contracts=self.root/'bad.json';contracts.write_text(json.dumps(data))
            self.invoke('analyze',source,'--call-contracts',contracts,code=2)


if __name__=='__main__':unittest.main()
