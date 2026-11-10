"""Serialized frozen development follow-up; preserves raw commands and failures."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

sys.path.insert(0, str(Path('tools').resolve()))
from effort_resources import measure, save, environment

root = Path(__file__).resolve().parent
protocol = json.loads((root / 'protocol.json').read_text())

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def check_bindings():
    for name, expected in protocol['bindings'].items():
        if sha(name) != expected:
            raise RuntimeError('changed frozen input: ' + name)

def run(label, argv):
    argv = list(map(str, argv))
    save(root / (label + '-command.json'), argv)
    print('START', label, flush=True)
    with (root / (label + '.log')).open('w') as log:
        result = subprocess.run(argv, text=True, stdout=log, stderr=subprocess.STDOUT)
    print('END', label, result.returncode, flush=True)
    if result.returncode:
        raise RuntimeError(f'{label} failed; raw log preserved')

check_bindings()
save(root / 'environment.json', environment())
proofs = []
for i, version in enumerate(protocol['proof_resource_comparison']['order']):
    directory = root / f'proof-{i}-{version}'
    argv = [root / ('csrd-' + version), 'transform', 'benchmarks/rich/development/jenkins_word.c',
            '-o', directory / 'candidate.c', '--strategy', 'limbs16', '--timeout-ms', '30000',
            '--report', directory / 'proof.json']
    resources = measure(argv, directory, wall_seconds=40, sample_seconds=0.01)
    report = json.loads((directory / 'proof.json').read_text()) if (directory / 'proof.json').is_file() else {}
    proof = report.get('functions', [{}])[0].get('proof', {})
    proofs.append({'index': i, 'version': version, 'resources': resources,
                   'verification': proof.get('status'), 'method': proof.get('solver_strategy'),
                   'steps': len(proof.get('steps', [])), 'candidate_sha256': report.get('candidate_sha256'),
                   'output_written': report.get('output_written')})
    save(root / 'proof-resources.json', proofs)
    print('PROOF', i, version, resources['status'], proof.get('status'), flush=True)
    if version == 'new' and (proof.get('status') != 'proved-under-model' or resources['status'] != 'completed'):
        raise RuntimeError('new proof failed; preserve attempt without admitting its output')
    if report and report.get('candidate_sha256') != protocol['candidate_source_sha256']:
        raise RuntimeError('generated C changed')

matrix_dir = Path('experiments/runs/jenkins-composition-matrix-linux-20261110')
run('matrix', [sys.executable, 'tools/run_matrix.py', '--matrix', 'experiments/rich-benchmarks.json',
              '--csrd', root / 'csrd-new', '--compiler', 'clang=clang-18', '--compiler', 'gcc=gcc',
              '--objdump', 'llvm-objdump-18', '--profdata', 'llvm-profdata-18', '--tier', 'extended',
              '--case', 'jenkins_word', '--strategies', 'identity', 'affine', 'limbs16', '--seeds', '42',
              '--inputs', '256', '--iterations', '1000000', '--repetitions', '7', '--timeout-ms', '30000',
              '--no-select', '--output-dir', matrix_dir])
matrix = matrix_dir / 'matrix.json'
run('sizes', [sys.executable, 'tools/measure_code_size.py', '--matrix-report', matrix,
             '--output-dir', root / 'linked-sizes'])

for observer in ('bitlinear', 'ghidra'):
    spec = protocol[observer]
    argv = [sys.executable, 'tools/measure_effort.py', '--matrix-report', matrix,
            '--csrd', root / 'csrd-new', '--observer', observer, '--case', 'jenkins_word',
            '--repetitions', str(spec['repetitions']), '--warmups', str(spec['warmups']),
            '--order-seed', str(spec['order_seed']), '--input-seed', str(spec['input_seed']),
            '--grading-seconds', str(spec['grading_seconds']), '--timeout-ms', '30000']
    for profile in spec['profiles']:
        argv += ['--profile', profile]
    for variant in spec['variants']:
        argv += ['--variant', variant]
    argv += ['--wall-budgets', *map(str, spec['wall_budgets'])]
    if observer == 'bitlinear':
        argv += ['--query-budgets', *map(str, spec['query_budgets'])]
    else:
        argv += ['--headless', '/work/experiments/runs/dependencies/ghidra_12.2_PUBLIC/support/analyzeHeadless',
                 '--analysis-seconds', str(spec['analysis_seconds']),
                 '--decompile-seconds', str(spec['decompile_seconds'])]
    argv += ['--output-dir', f'experiments/runs/jenkins-composition-{observer}-linux-20261110']
    run(observer, argv)
check_bindings()
print('COMPLETE; bindings unchanged', flush=True)
