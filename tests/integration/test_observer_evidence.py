"""Reject broken identity, grading, repetition and observation-model links."""
import json
import shutil
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
from audit_protection import file_hash
from check_buffer_evidence import check_replay
from pcode_memory import reconstruct
from replay_buffer_observers import reuse_collection_grade


class ReplayEvidence(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = self.root = Path(self.temp.name)
        self.matrix_path, self.replay_path = root/'matrix.json', root/'replay.json'
        export = {'status':'decompiled', 'schema_version':4, 'memory_model':'ordered-u32-buffers-v1',
                  'function':'f', 'arity':2, 'parameters':[{'kind':'uint32', 'read_only':False},
                                                         {'kind':'uint32-buffer', 'read_only':False}],
                  'address_space':{'id':433, 'pointer_bytes':8, 'addressable_unit_bytes':1},
                  'entry_block':0, 'operation_order':'basic-block-live-order',
                  'nodes':[{'size':4, 'input':True, 'parameter':0}, {'size':8, 'constant':'0'},
                           {'size':8, 'input':True, 'parameter':1}],
                  'operations':[{'opcode':'RETURN', 'block':0, 'inputs':[1,0]}],
                  'blocks':[{'id':0, 'incoming':[], 'outgoing':[], 'operations':[0]}]}
        self.write(root/'export.json', export)
        metrics = {}
        candidate = root/'0/adapter/recovered.c'; candidate.parent.mkdir(parents=True)
        candidate.write_text(reconstruct(export, metrics=metrics))
        reference = root/'original.c'; reference.write_text('unsigned f(unsigned x,unsigned*p){(void)p;return x;}\n')
        tool = root/'csrd'; tool.write_text('test checker artifact; no execution or proof is claimed\n')
        self.row = {'attempt':0, 'prior_attempt':0, 'repetition':0, 'group':0, 'function':'f',
                    'profile':'clang-O2', 'variant':'affine', 'binary_sha256':'fixture-binary',
                    'export_path':str(root/'export.json'), 'export_sha256':file_hash(root/'export.json'),
                    'status':'recovered-under-source-model', 'verification':'proved-under-model',
                    'semantic_model':'test-checker-model', 'recovered_path':str(candidate),
                    'recovered_sha256':file_hash(candidate), 'controls':{'return-plus-one':'counterexample'}}
        self.matrix = {'status':'failed', 'schedule':[[0,0,0]], 'observations':[dict(self.row)],
                       'groups':[{'reference':str(reference), 'reference_sha256':file_hash(reference)}]}
        self.write(self.matrix_path, self.matrix)
        resources = {'status':'completed', 'argv':['python3', '--export', str(root/'export.json')]}
        self.write(root/'0/resources/resources.json', resources); self.row['resources'] = resources
        adapter = {'status':'candidate', 'export_sha256':self.row['export_sha256'], 'metrics':metrics,
                   'recovered_sha256':file_hash(candidate)}
        self.write(root/'0/adapter/adapter.json', adapter); self.row['adapter'] = adapter
        self.proof = {'source_sha256':file_hash(reference), 'candidate_sha256':file_hash(candidate),
                      'functions':[{'function':'f', 'verification':'proved-under-model', 'semantic_model':'test-checker-model'}]}
        proof_path = root/'0/verification.json'; self.write(proof_path, self.proof)
        self.row.update(proof_path=str(proof_path), proof_sha256=file_hash(proof_path))
        wrong = root/'0/return-plus-one.c'; wrong.write_text(reconstruct(export, result_offset=1))
        self.write(root/'0/return-plus-one.json', {'source_sha256':file_hash(reference), 'candidate_sha256':file_hash(wrong),
                   'functions':[{'function':'f', 'verification':'counterexample'}]})
        self.replay = {'status':'completed', 'input_report':str(self.matrix_path), 'input_sha256':file_hash(self.matrix_path),
                       'adapter_hashes':{}, 'csrd':str(tool), 'csrd_sha256':file_hash(tool), 'repetitions':1,
                       'records':[self.row], 'outcomes':{'recovered-under-source-model':1}, 'distinct_graded_answers':1}
        self.save()

    def tearDown(self): self.temp.cleanup()

    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def save(self): self.write(self.replay_path, self.replay)

    def check(self): return check_replay(self.replay_path, self.matrix_path)

    def test_failed_old_grade_retained_with_separate_replay(self):
        result = self.check()
        self.assertEqual(result['original_status_retained'], 'failed')
        self.assertEqual(result['recovered_observations'], 1)
        self.assertEqual(result['rejected_controls'], 1)

    def test_collection_grades_reused_only_for_exact_answers_and_controls(self):
        source=self.root/'attempt-0';shutil.copytree(self.root/'0',source)
        folder=self.root/'new';folder.mkdir()
        wrong='return-plus-one';shutil.copyfile(source/(wrong+'.c'),folder/(wrong+'.c'))
        args=(self.root,self.matrix['observations'][0],self.row,self.matrix['groups'][0],folder,{wrong:{'result_offset':1}})
        proof,controls=reuse_collection_grade(*args)
        self.assertEqual(proof['verification'],'proved-under-model')
        self.assertEqual(controls,{wrong:'counterexample'})
        # Inconclusive judgments remain inconclusive when reused.
        self.matrix['observations'][0]['verification']='inconclusive'
        self.proof['functions'][0]['verification']='inconclusive'
        self.write(source/'verification.json',self.proof)
        self.assertEqual(reuse_collection_grade(*args)[0]['verification'],'inconclusive')
        self.proof['candidate_sha256']='different-answer';self.write(source/'verification.json',self.proof)
        with self.assertRaisesRegex(ValueError,'grading identity'):reuse_collection_grade(*args)
        (folder/(wrong+'.c')).write_text('changed corruption control')
        self.assertIsNone(reuse_collection_grade(*args))

    def test_duplicate_repetition_rejected(self):
        self.replay['records'].append(dict(self.row)); self.save()
        with self.assertRaisesRegex(ValueError, 'duplicate replay'): self.check()

    def test_missing_repetition_rejected(self):
        self.replay['repetitions'] = 2; self.save()
        with self.assertRaisesRegex(ValueError, 'missing/duplicate replay'): self.check()

    def test_relabelled_proof_rejected(self):
        self.proof['functions'][0]['verification'] = 'counterexample'
        self.write(Path(self.row['proof_path']), self.proof)
        self.row['proof_sha256'] = file_hash(self.row['proof_path']); self.save()
        with self.assertRaisesRegex(ValueError, 'proof selection/status'): self.check()

    def test_observation_model_cannot_be_silently_changed(self):
        self.replay['recursion_observation'] = 'bounded-body'; self.save()
        with self.assertRaisesRegex(ValueError, 'observation model'): self.check()

    def test_bounded_body_result_keeps_its_qualified_label(self):
        self.replay['recursion_observation'] = 'bounded-body'
        self.row['semantic_model'] = 'bounded-recursion-body-c11-v1'
        self.row['status'] = 'recovered-under-bounded-recursion'
        self.replay['outcomes'] = {self.row['status']:1}
        self.proof['functions'][0]['semantic_model'] = self.row['semantic_model']
        self.proof['verification_recursion_observation'] = 'bounded-body'
        self.write(Path(self.row['proof_path']), self.proof)
        self.row['proof_sha256'] = file_hash(self.row['proof_path'])
        path = self.root/'0/return-plus-one.json'; control = json.loads(path.read_text())
        control['verification_recursion_observation'] = 'bounded-body'; self.write(path, control)
        self.save()
        self.assertEqual(self.check()['outcomes'], {'recovered-under-bounded-recursion':1})
        self.row['status'] = 'recovered-under-source-model'; self.save()
        with self.assertRaisesRegex(ValueError, 'classification changed'): self.check()

    def test_missing_control_rejected(self):
        self.row['controls'] = {}; self.save()
        with self.assertRaisesRegex(ValueError, 'missing replay corruption'): self.check()

    def test_changed_candidate_rejected(self):
        Path(self.row['recovered_path']).write_text('unsigned f(unsigned x){return x+1;}')
        with self.assertRaisesRegex(ValueError, 'artifact hash mismatch'): self.check()


if __name__ == '__main__': unittest.main()
