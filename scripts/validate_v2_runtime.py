"""Explicit real-provider VR/Ultra and QML resume verification on synthetic data."""
from __future__ import annotations
import argparse
import json
import os
import threading
import time
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_CONTROLS_STYLE', 'Basic')
os.environ.setdefault('QSG_RHI_BACKEND', 'software')

from PySide6.QtCore import QSettings, QObject, Qt, QPoint
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.models import KnowledgeDocument
from vrsoft_extractor.mary.orchestrator import ChatOrchestrator
from vrsoft_extractor.mary.frontend.chat import ChatBridge
from vrsoft_extractor.mary.frontend.bridge import FrontendBridge
from vrsoft_extractor.mary.frontend.studio import StudioBridge
from vrsoft_extractor.mary.frontend.app import create_engine, _apply_application_font


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--provider', default='antigravity')
    parser.add_argument('--output', type=Path, default=Path('reports/v2/conclusao/runtime'))
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    settings = MarySettings(app_dir=output, root=output/'VRProject', old_root=output/'legacy')
    settings.ensure_dirs()
    db = MaryDatabase(settings.database_path, root=settings.root)
    db.upsert_document(KnowledgeDocument('wiki', 'v2-reserva', 'Procedimento sintético de reserva para retirada',
        'https://fixture.invalid/reserva', markdown='''# Procedimento sintético de reserva para retirada
Este documento é uma fixture, não uma instrução do ERP real.
1. Abra o pedido, selecione os produtos e informe as quantidades solicitadas.
2. Confirme a reserva para tornar essas quantidades indisponíveis para outra venda.
3. Na retirada, confira cada item e sua quantidade antes de concluir a entrega.
4. Se o pedido for cancelado, libere a reserva para devolver as quantidades ao saldo disponível.
A reserva não confirma pagamento. Confira o pagamento separadamente.
''', module='PDV', review_status='approved'))
    orchestrator = ChatOrchestrator(settings, db)
    provider = orchestrator.providers[args.provider]
    models = provider.list_models()
    if not models:
        raise RuntimeError('Conta/runtime sem modelos disponíveis')
    item = next((m for m in models if m.get('isDefault')), models[0])
    model = str(item.get('model') or item.get('id'))
    report = {'provider': args.provider, 'model': model, 'runs': {}}
    question = 'Segundo o procedimento sintético, como reservar produtos para retirada, conferir a entrega e liberar o saldo se o pedido for cancelado?'
    cancelled_run = None
    try:
        for mode in ('vr', 'ultra', 'cancel'):
            cid = orchestrator.new_conversation(args.provider, model, 'low', workspace=settings.work_dir,
                vr_mode='vr' if mode == 'vr' else 'ultra', approval_profile='supervised')
            done = threading.Event()
            events = []
            cancelled = False
            def callback(event):
                nonlocal cancelled
                events.append({'kind': event.kind, 'text': event.text, 'execution_id': event.payload.get('execution_id'),
                               'run_id': event.payload.get('run_id'), 'reused': event.payload.get('reused')})
                if mode == 'cancel' and event.kind == 'agent_completed' and not cancelled:
                    cancelled = True
                    orchestrator.interrupt(cid)
                if event.kind == 'turn_completed':
                    done.set()
            started = time.monotonic()
            orchestrator.send(cid, question, callback, vr_mode='vr' if mode == 'vr' else 'ultra')
            while not done.wait(1):
                if time.monotonic() - started > 180:
                    orchestrator.interrupt(cid)
                    raise TimeoutError('Turno ultrapassou o limite do teste')
            with db.connect() as conn:
                citations = [dict(r) for r in conn.execute('SELECT * FROM source_citations WHERE conversation_id=?', (cid,))]
                runs = [dict(r) for r in conn.execute('SELECT * FROM research_runs WHERE conversation_id=?', (cid,))]
            report['runs'][mode] = {'seconds': round(time.monotonic()-started, 2), 'conversation_id': cid,
                'messages': [dict(m) for m in db.messages(cid)], 'citations': citations, 'research_runs': runs, 'events': events}
            (output/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(mode, {'seconds': report['runs'][mode]['seconds'], 'citations': len(citations), 'statuses': [r['status'] for r in runs]}, flush=True)
            if mode == 'cancel':
                cancelled_run = orchestrator.research_repository.latest_resumable(cid)
                if not cancelled_run or cancelled_run['status'] != 'cancelled':
                    raise RuntimeError('Pesquisa não alcançou o checkpoint cancelado')
    finally:
        orchestrator.close()

    app = QApplication.instance() or QApplication([])
    _apply_application_font(app)
    prefs = QSettings(str(output/'ui.ini'), QSettings.IniFormat)
    chat = ChatBridge(settings, db, prefs)
    frontend = FrontendBridge(settings, prefs, theme_override='dark_orange', initial_page='Chat VR')
    studio = StudioBridge(settings, db, prefs)
    engine = create_engine(frontend, chat, studio)
    try:
        if not engine.rootObjects():
            raise RuntimeError('QML não carregou')
        window = engine.rootObjects()[0]
        window.setWidth(1366)
        window.setHeight(768)
        index = next(i for i, row in enumerate(chat._conversations._items) if row['conversationId'] == cid)
        chat.selectConversation(index)
        QTest.qWait(300)
        window.grabWindow().save(str(output/'resume-before.png'))
        button = window.findChild(QObject, 'resumeResearchButton')
        if not button or not button.property('enabled'):
            raise RuntimeError('Ação de retomada não disponível')
        point = button.mapToScene(button.boundingRect().center())
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(round(point.x()), round(point.y())))
        started = time.monotonic()
        while time.monotonic()-started < 180:
            QTest.qWait(30)
            row = db.get_conversation(cid)
            if row['active_execution_id'] != cancelled_run['execution_id'] and row['status'] != 'running' and not chat.turnRunning:
                break
        repository = chat._orchestrator.research_repository
        after = repository.get_run(cancelled_run['run_id'])
        steps = repository.get_steps_for_run(after['run_id'])
        assistants = [dict(m) for m in db.messages(cid) if m['role'] == 'assistant']
        report['resume'] = {'before': cancelled_run, 'after': after, 'steps': steps, 'assistants': assistants,
            'same_run': after['run_id'] == cancelled_run['run_id'], 'new_execution': after['execution_id'] != cancelled_run['execution_id'],
            'reused': any(s['status'] == 'reused' for s in steps), 'qml_warnings': [w.toString() for w in engine._qml_warnings]}
        report['resume']['ui_idle'] = not chat.turnRunning
        window.grabWindow().save(str(output/'resume-after.png'))
        (output/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        checks = report['resume']
        if not (checks['same_run'] and checks['new_execution'] and checks['reused'] and checks['ui_idle'] and after['status'] == 'completed' and after['publication_message_id'] and len(assistants) == 1):
            raise RuntimeError('Retomada não passou; consulte result.json')
        print('Retomada pela UI aprovada: mesmo run, nova execução, checkpoint reutilizado, uma publicação.', flush=True)
    finally:
        studio.close()
        chat.close()
        engine.deleteLater()
        app.processEvents()


if __name__ == '__main__':
    main()
