from pathlib import Path
import hashlib,json,shutil,tarfile,datetime
root=Path.cwd().resolve()
probes=root/'experiments/runs/solver-probes-20261110'
final=root/'experiments/runs/graded-circuits-final-20261110'
pilot=root/'experiments/runs/graded-circuits-20261110'
out=root/'reports/circuit-evidence-20261110';out.mkdir(exist_ok=False)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def copy(source,name=None):shutil.copyfile(source,out/(name or source.name))
def archive(name,files):
    files=sorted(set(files))
    with tarfile.open(out/name,'w:xz',preset=6) as tar:
        for p in files:
            if p.is_symlink():raise ValueError('unexpected symlink '+str(p))
            tar.add(p,arcname=str(p.relative_to(root)),recursive=False)
    return [{'path':str(p.relative_to(root)),'sha256':sha(p),'bytes':p.stat().st_size} for p in files]
def tree(path):return [p for p in path.rglob('*') if p.is_file()]
copy(final/'summary.json');copy(final/'protocol.json');copy(final/'completion.json')
copy(pilot/'summary.json','failed-pilot-summary.json');copy(pilot/'completion.json','failed-pilot-completion.json')
copy(probes/'results/summary.json','solver-portfolio-summary.json');copy(probes/'results/protocol.json','solver-portfolio-protocol.json')
copy(probes/'dependencies.json');copy(probes/'archive.py')
for p in probes.glob('tests-*.log'):copy(p)
copy(probes/'abc-src/copyright.txt','ABC-COPYRIGHT.txt')
copy(root/'experiments/grade_saved_answers.py');copy(root/'tools/verify_circuit.py')
manifest={}
manifest['replay.tar.xz']=archive('replay.tar.xz',tree(final))
manifest['failed-pilot.tar.xz']=archive('failed-pilot.tar.xz',tree(pilot))
probe_files=[]
for p in probes.iterdir():
    if p.name in ('venv','abc-src'):continue
    probe_files.extend(tree(p) if p.is_dir() else [p])
manifest['exploratory-probes.tar.xz']=archive('exploratory-probes.tar.xz',probe_files)
protocol=json.loads((final/'protocol.json').read_text())
files=[]
prior=root/'experiments/runs/jenkins-composition-ghidra-linux-20261110'
files.extend(prior.glob('trial-*/trial.json'))
for case in protocol['cases']:
    if 'binding' not in case:continue
    b=case['binding'];p=root/b['grade_report'];files+=[p,p.parent/'measurement/command.json']
    files.extend(root/item['path'] for item in b['files'])
manifest['frozen-inputs.tar.xz']=archive('frozen-inputs.tar.xz',files)
manifest['native-tools.tar.xz']=archive('native-tools.tar.xz',[probes/'abc-src/abc',probes/'abc-src/copyright.txt',root/'build/csrd-query-circuit',root/'LICENSE'])
with tarfile.open(out/'file-manifests.tar.xz','w:xz',preset=6) as tar:
    import io
    data=(json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode();info=tarfile.TarInfo('file-manifests.json');info.size=len(data);tar.addfile(info,io.BytesIO(data))
index={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
       'implementation_commits':['eabc8bd','b69f68e'],
       'scope':'saved-query grading and exploratory probes; not new observer measurements',
       'external_dependencies':'ABC source and Bitwuzla wheel are identified by revision/version/hash in dependencies.json; vendored source/venv excluded; native tools and ABC license retained',
       'archives':{name:{'files':len(items),'uncompressed_file_bytes':sum(x['bytes'] for x in items)} for name,items in manifest.items()},
       'files':{p.name:{'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(out.iterdir()) if p.is_file()}}
(out/'sha256.json').write_text(json.dumps(index,indent=2,sort_keys=True)+'\n')
print('archived',len(index['files']),'files',sum(x['bytes'] for x in index['files'].values()),flush=True)
