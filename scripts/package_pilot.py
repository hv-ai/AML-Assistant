"""Build an allowlisted deployment ZIP; never include credentials/runtime data."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
FILES=['app.py','hosted.py','gunicorn.conf.py','configure.py','requirements.txt','render.yaml','.replit',
       '.gitignore','.env.example','README.md','DEPLOYMENT.md','data/processed/chunks.json','data/news_archive.json']
for pattern in ['src/*.py','web/*','config/*.json','evaluation/*','tests/*.py','scripts/package_pilot.py']:
    FILES.extend(str(p.relative_to(ROOT)) for p in ROOT.glob(pattern) if p.is_file())
FILES.extend('reports/'+name for name in ['retrieval_comparison.json','retrieval_comparison.csv',
    'retrieval_comparison_initial_labels.json','answer_comparison.json','answer_comparison_small_model.json',
    'aml_typology_coverage.html','aml_typology_coverage.json','revision_final_answers.json',
    'revision_answer_checks.json','adversarial_checks.json','public_latency_before.json','revision_acceptance.json','current_source_revision.json','redflag_ui_check.json'])
FILES.extend(str(p.relative_to(ROOT)) for p in (ROOT/'data/raw').glob('S*.json'))
# Checksum tests and provenance verification need the captured originals too.
for catalog in ('typology_sources.json','customer_control_sources.json'):
    FILES.extend(s['original_path'] for s in json.loads((ROOT/'config'/catalog).read_text()))

def package():
    secrets=[]
    env=ROOT/'.env'
    if env.exists():
        for line in env.read_text().splitlines():
            if '=' in line:
                key,value=line.split('=',1)
                if ('KEY' in key or 'SECRET' in key) and len(value.strip())>12:secrets.append(value.strip().strip('\"\''))
    blobs=[]
    for name in sorted(set(FILES)):
        path=ROOT/name
        if path.is_symlink() or not path.is_file():raise RuntimeError('Missing or unsupported distribution file: '+name)
        data=path.read_bytes()
        if any(value.encode() in data for value in secrets):raise RuntimeError('Credential found in distribution file; package not created.')
        blobs.append((name,data))
    output=ROOT/'dist/aml-review-desk-pilot.zip';output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,data in blobs:archive.writestr(name,data)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip():raise RuntimeError('Archive validation failed.')
        with tempfile.TemporaryDirectory() as folder:
            archive.extractall(folder)
            verified=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-q'],cwd=folder,capture_output=True,text=True)
            if verified.returncode:raise RuntimeError('Tests failed in the clean deployment archive:\n'+verified.stderr)
            print(verified.stderr.strip())
    print('Created',output,'with',len(blobs),'allowlisted files. No configured credentials or runtime data included.')
    return output

if __name__=='__main__':package()
