"""Post-run proof-chain probe. Does not change or rerun the frozen observer."""
from pathlib import Path
import hashlib
import json
import sys

sys.path.insert(0, str(Path('tools').resolve()))
from effort_resources import measure, save
from audit_decompiler import scoring_reference

root = Path(__file__).resolve().parent
out = root / 'grading-chain-probe'
out.mkdir(exist_ok=False)
matrix_path = Path('experiments/runs/jenkins-composition-matrix-linux-20261110/matrix.json')
matrix = json.loads(matrix_path.read_text())
run_dir = Path('experiments/runs/jenkins-composition-ghidra-linux-20261110')
run = json.loads((run_dir / 'effort.json').read_text())
if run['status'] != 'completed':
    raise RuntimeError('frozen observer run must be complete')

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

csrd = root / 'csrd-new'
if sha(csrd) != matrix['tools']['csrd']['sha256']:
    raise RuntimeError('verifier differs from frozen matrix')
save(out / 'protocol.json', {'scope':'post-run probe, no observer rerun or historical reclassification',
    'selection':'lowest measured inconclusive limb trial id per O2 compiler',
    'solver_ms_per_link':30000,'wall_seconds_per_link':45,
    'matrix_sha256':sha(matrix_path),'effort_sha256':sha(run_dir/'effort.json'),'csrd_sha256':sha(csrd)})

def compare(label, left, right):
    directory = out / label
    left_hash, right_hash = sha(left), sha(right)
    resources = measure([csrd,'verify',left,right,'--timeout-ms','30000','--report',directory/'proof.json'],
                        directory,wall_seconds=45)
    report = json.loads((directory/'proof.json').read_text()) if (directory/'proof.json').is_file() else {}
    functions = report.get('functions',[])
    status = functions[0]['verification'] if len(functions)==1 else 'inconclusive'
    if resources['status'] not in ('completed','nonzero-exit') or (status=='proved-under-model' and resources['status']!='completed'):
        status='inconclusive'
    if report and (report['source_sha256']!=left_hash or report['candidate_sha256']!=right_hash):
        raise RuntimeError('proof not bound to selected artifacts')
    if sha(left)!=left_hash or sha(right)!=right_hash:
        raise RuntimeError('proof input changed')
    return {'status':status,'resources':resources,'left_sha256':left_hash,'right_sha256':right_hash,
            'report':str(directory/'proof.json'),'report_sha256':sha(directory/'proof.json') if report else None}

rows=[]
for profile in ('clang-O2','gcc-O2'):
    choices=[]
    for p in sorted(run_dir.glob('trial-*/trial.json')):
        t=json.loads(p.read_text())
        if t['repetition']>=0 and t['variant']=='limbs16' and t['profile']==profile and t['status']=='inconclusive':
            choices.append(t)
    if not choices:
        rows.append({'profile':profile,'status':'no-eligible-inconclusive-answer'}); continue
    trial=choices[0]
    record=next(r for r in matrix['records'] if r['profile']==profile and r['variant']=='limbs16')
    reference,reference_hash=scoring_reference(matrix,record)
    built=Path(record['binary']).parent/'function.i'
    candidate=Path(trial['directory'])/'observer/candidate.c'
    mutant=Path(trial['directory'])/'mutant.c'
    if sha(built)!=record['preprocessed_sha256'] or sha(candidate)!=trial['candidate_sha256']:
        raise RuntimeError('selected candidate/build input changed')
    bridge=compare(profile+'-bridge',reference,built)
    row={'profile':profile,'trial_id':trial['id'],'original_status':trial['status'],'bridge':bridge}
    if bridge['status']=='proved-under-model':
        row['answer']=compare(profile+'-answer',built,candidate)
        row['negative_control']=compare(profile+'-negative',built,mutant)
        row['status']='proved-via-chain' if row['answer']['status']=='proved-under-model' and row['negative_control']['status']=='counterexample' else 'inconclusive'
    else:
        row['status']='inconclusive'
    rows.append(row)
    save(out/'results.json',rows)
    print(profile,row['status'],{k:row[k]['status'] for k in ('bridge','answer','negative_control') if k in row},flush=True)
save(out/'results.json',rows)
