"""Explicit bounded smoke through the available real provider transports."""
import argparse
import json
from pathlib import Path
import threading
import time
from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.orchestrator import ChatOrchestrator

parser = argparse.ArgumentParser()
parser.add_argument('provider', choices=['codex','claude','opencode','antigravity'])
args = parser.parse_args()
output = Path('reports/v2/conclusao/adapters')/args.provider
output.mkdir(parents=True,exist_ok=True)
settings = MarySettings(app_dir=output.resolve(),root=(output/'VRProject').resolve(),old_root=(output/'legacy').resolve())
settings.ensure_dirs()
db = MaryDatabase(settings.database_path, root=settings.root)
orchestrator = ChatOrchestrator(settings,db)
report = {'provider':args.provider,'events':[],'passed':False}
started = time.monotonic()
try:
    provider = orchestrator.providers[args.provider]
    report['available'] = provider.available()
    models = provider.list_models()
    report['model_count'] = len(models)
    chosen = next((m for m in models if m.get('isDefault')), models[0])
    model = str(chosen.get('model') or chosen.get('id'))
    report['model'] = model
    cid = orchestrator.new_conversation(args.provider,model,'low',workspace=settings.work_dir,vr_mode='off',approval_profile='readonly')
    done = threading.Event()
    def callback(event):
        if event.kind in {'error','assistant_completed','token_usage','turn_completed'}:
            report['events'].append({'kind':event.kind,'text':event.text,'payload':event.payload})
        if event.kind == 'turn_completed':
            done.set()
    orchestrator.send(cid,'Responda somente V2_OK. Não use ferramentas.',callback,vr_mode='off')
    if not done.wait(60):
        orchestrator.interrupt(cid)
        raise TimeoutError('Provider smoke exceeded 60 seconds')
    messages = [dict(m) for m in db.messages(cid) if m['role']=='assistant']
    report['responses'] = [m['content'] for m in messages]
    report['passed'] = any('V2_OK' in m['content'] for m in messages) and not any(e['kind']=='error' for e in report['events'])
except Exception as exc:
    report['error'] = str(exc)
finally:
    report['seconds'] = round(time.monotonic()-started,2)
    (output/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print({k:v for k,v in report.items() if k!='events'},flush=True)
    orchestrator.close()
