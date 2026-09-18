"""Archive, extract and launch the actual frozen GUI with isolated project data."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import time
import zipfile

root = Path(__file__).resolve().parents[1]
output = root/'reports/v2/conclusao'
parser = argparse.ArgumentParser()
parser.add_argument('--final', action='store_true')
args = parser.parse_args()
package = output/('package-final/VRNorteStudio' if args.final else 'package/VRNorteStudio')
archive = output/('VRStudio-v2-final.zip' if args.final else 'VRStudio-v2-validation.zip')
extracted = output/('portable-extracted-final' if args.final else 'portable-extracted')
report = {'package':str(package), 'archive':str(archive), 'launches':[]}
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_STORED if args.final else zipfile.ZIP_DEFLATED, compresslevel=1) as z:
    for path in sorted(package.rglob('*')):
        if path.is_file():
            z.write(path, path.relative_to(package.parent))
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    z.extractall(extracted)
print('Archive created and extracted', flush=True)
digest = hashlib.sha256()
with archive.open('rb') as stream:
    for chunk in iter(lambda:stream.read(1024*1024), b''):
        digest.update(chunk)
report.update(archive_sha256=digest.hexdigest(), archive_bytes=archive.stat().st_size,
              extracted_bytes=sum(p.stat().st_size for p in extracted.rglob('*') if p.is_file()))
exe = extracted/'VRNorteStudio/VRNorteStudio.exe'
env = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software', QT_QUICK_CONTROLS_STYLE='Basic')
for theme, page, tab in [('dark_orange','Chat VR',-1),('light','Configurações',2)]:
    suffix = '-final' if args.final else ''
    app_dir = output/f'portable-data-{theme}{suffix}'
    app_dir.mkdir(exist_ok=True)
    screenshot = output/f'portable-{theme}{suffix}.png'
    command = [str(exe), '--project-dir', str(app_dir), '--vr-root', str(app_dir/'VRProject'),
        '--screenshot', str(screenshot), '--screenshot-theme', theme, '--screenshot-page', page,
        '--screenshot-width', '1366', '--screenshot-height', '768', '--screenshot-settings-tab', str(tab)]
    start = time.monotonic()
    result = subprocess.run(command, cwd=extracted, env=env, timeout=90, capture_output=True,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    log = (result.stdout or b'') + (result.stderr or b'')
    (output/f'portable-{theme}{suffix}.log').write_bytes(log)
    report['launches'].append({'theme':theme,'page':page,'exit':result.returncode,'seconds':round(time.monotonic()-start,2),
        'screenshot':str(screenshot), 'screenshot_bytes':screenshot.stat().st_size if screenshot.exists() else 0,
        'implicit_model_download': any((app_dir/'VRProject/tools/embeddings').rglob('*.onnx'))})
    (output/f'portable-result{suffix}.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    assert result.returncode == 0 and screenshot.exists(), report['launches'][-1]
    assert not report['launches'][-1]['implicit_model_download']
    print(report['launches'][-1], flush=True)
