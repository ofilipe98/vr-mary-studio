"""Reproducible static checks and an explicit source inventory, without private data."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

root = Path(__file__).resolve().parents[1]
output = root/'reports/v2/conclusao'
parser = argparse.ArgumentParser()
parser.add_argument('--snapshot', action='store_true')
args = parser.parse_args()
if args.snapshot:
    names = subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'], cwd=root).decode().split('\0')
    allowed_roots = {'vrsoft_extractor','tests','scripts','docs','installer'}
    allowed_files = {'.env.example','pyproject.toml','VRNorteStudio.spec','VRNorteStudio.pyw','README.md','AGENTS.md','.gitignore'}
    suffixes = {'.py','.pyw','.qml','.json','.md','.toml','.txt','.spec','.ps1','.cmd','.svg','.png','.ico','.qrc','.js'}
    manifest = []
    with zipfile.ZipFile(output/'source-final.zip','w',zipfile.ZIP_DEFLATED) as z:
        for name in sorted(set(names)):
            path = root/name
            if not name or not path.is_file() or '__pycache__' in path.parts:
                continue
            if not (name in allowed_files or (Path(name).parts[0] in allowed_roots and path.suffix in suffixes)):
                continue
            data = path.read_bytes()
            manifest.append({'path':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
            z.writestr(name,data)
    (output/'source-final-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    for command, filename in [(['git','status','--porcelain=v1','--untracked-files=all'],'git-status-final.txt'),
                              (['git','diff','--no-ext-diff','--','vrsoft_extractor','tests','scripts','pyproject.toml','VRNorteStudio.spec'],'tracked-diff-final.patch')]:
        (output/filename).write_bytes(subprocess.check_output(command,cwd=root))
    print(f'Snapshotted {len(manifest)} source and documentation files')
else:
    qml = root/'vrsoft_extractor/mary/frontend/qml'
    lint = root/'.venv/Lib/site-packages/PySide6/qmllint.exe'
    records = []
    for path in sorted(qml.rglob('*.qml')):
        process = subprocess.run([str(lint),'-I',str(qml),str(path)],capture_output=True,text=True,encoding='utf-8',errors='replace',cwd=root)
        text = process.stdout + process.stderr
        records.append({'file':path.relative_to(root).as_posix(),'exit':process.returncode,
                        'warnings':len(re.findall(r'^Warning:',text,re.M)), 'errors':len(re.findall(r'^Error:',text,re.M)),
                        'categories':re.findall(r'^Warning:.*?\[([^]]+)\]$',text,re.M),'output':text})
    (output/'qmllint-final.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    checks = {}
    for command, name in [([sys.executable,'-m','compileall','-q','vrsoft_extractor'],'compileall'),
                          ([sys.executable,'-m','ruff','check','vrsoft_extractor/mary','--select','F821,F811'],'ruff'),
                          (['git','-c','core.safecrlf=false','diff','--check'],'diff-check')]:
        p = subprocess.run(command,capture_output=True,cwd=root)
        checks[name] = {'exit':p.returncode,'output':(p.stdout+p.stderr).decode('utf-8',errors='replace')}
    summary = {'qml_files':len(records),'qml_errors':sum(r['errors'] for r in records),
               'qml_warnings':sum(r['warnings'] for r in records),'python_and_diff':checks}
    (output/'static-final.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False),flush=True)
