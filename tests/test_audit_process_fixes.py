from unittest.mock import patch
import json
import shutil
import pytest
import test_mary_vr_ultra as fixture
from vrsoft_extractor.mary.models import EvidenceCandidate, EvidenceBundle, QueryProfile, RuntimeEvent
from vrsoft_extractor.mary.providers import CodexProvider
from vrsoft_extractor.mary.providers import OpenCodeProvider, ProviderRateLimited
from vrsoft_extractor.mary.orchestrator import _code_scope_queries
from vrsoft_extractor.mary.supervision import parse_worker_report, FinalDraft, ResponseContract, validate_fanout_draft
from vrsoft_extractor.mary.evidence_reads import capture_read


def test_symbols_survive_instruction_prefix():
    q='Alvo exclusivo fontes locais permitidas descompilado sources schema conhecimento AlteraLojaDestinoCrossDockingGUI salvar'
    assert _code_scope_queries(q)[0] == 'AlteraLojaDestinoCrossDockingGUI'


def test_anonymous_old_event_cannot_finish_new_turn():
    p=CodexProvider();events=[]
    p._native_to_local['thread']='c';p._callbacks['c']=events.append
    p._active_turns['c']='t2';p._completed_turn_ids['thread']={'t1'}
    for method in ['item/agentMessage/delta','turn/completed']:
        p._handle_server_message({'method':method,'params':{'threadId':'thread','delta':'STALE'}})
    assert not events and p._active_turns['c']=='t2' and 'c' in p._callbacks


def test_known_current_item_can_correlate_delta_without_turn():
    p=CodexProvider();events=[]
    p._native_to_local['thread']='c';p._callbacks['c']=events.append;p._active_turns['c']='t2'
    p._handle_server_message({'method':'item/started','params':{'threadId':'thread','turnId':'t2','item':{'id':'i','type':'agentMessage'}}})
    p._handle_server_message({'method':'item/agentMessage/delta','params':{'threadId':'thread','itemId':'i','delta':'current'}})
    assert events[-1].text=='current'


def test_valid_id_is_not_semantic_support():
    report=parse_worker_report(json.dumps({'findings':[{'claim':'Enabled','kind':'fact','confidence':.99,'evidence_ids':['known']}]}),worker_id='w',worker_name='w',allowed_evidence_ids=['known'])
    assert report.findings[0].kind=='inference'
    assert report.findings[0].confidence<=.65
    assert report.findings[0].support_status=='UNVERIFIED'


def test_partial_answer_requires_sources_but_not_unanswerable_sections():
    c=EvidenceCandidate('known','schema','s',1,1,'schema','table','section','','','numeric(12,3)')
    bundle=EvidenceBundle(QueryProfile(query='q',intents={}),candidates=(c,))
    contract=ResponseContract('guidance','user','low','high',requires_sources=True,minimum_words=100,minimum_steps=5)
    assert not validate_fanout_draft(FinalDraft('Quantidade: numeric(12,3). Método ausente.',('known',),'partially_answered'),contract,bundle)
    assert validate_fanout_draft(FinalDraft('Unsupported',(),'partially_answered'),contract,bundle)


def test_read_capture_uses_real_file_and_rejects_unknown_path(tmp_path):
    path=tmp_path/'code.java';path.write_text('class X {\n void insert() {}\n}',encoding='utf8')
    c=EvidenceCandidate('known','code','s',0,0,'X','X','java','','','class X',local_path='code.java')
    e=RuntimeEvent('c','tool_event',payload={'part':{'tool':'read','state':{'status':'completed','input':{'filePath':str(path)},'output':'FABRICATED'}}})
    got=capture_read(e,tmp_path,[c])
    assert 'void insert()' in got.excerpt and 'FABRICATED' not in got.excerpt and 'SHA-256' in got.title
    assert capture_read(e,tmp_path,[]) is None


@pytest.mark.parametrize('failure',['partial_move','rollback','commit_after'])
def test_trash_reconciles_failure_and_preserves_journal(tmp_path,failure):
    settings,db,orch,_,cid,_=fixture._orchestrator(tmp_path,'ultra')
    source=settings.resolve_path(db.get_conversation(cid)['workspace']);(source/'keep').write_text('safe')
    original_move=shutil.move;original_update=db.update_conversation
    def move(src,dst):
        if failure=='rollback' and '.trash' in str(src):raise PermissionError('rollback')
        result=original_move(src,dst)
        if failure=='partial_move' and '.trash' in str(dst):raise PermissionError('partial')
        return result
    def update(*a,**kw):
        if failure=='commit_after':original_update(*a,**kw)
        raise RuntimeError('update')
    try:
        with patch.object(orch,'_sync_codex_lifecycle',return_value=True),patch('shutil.move',side_effect=move):
            if failure=='partial_move':
                with pytest.raises(PermissionError):orch.trash(cid)
            else:
                with patch.object(db,'update_conversation',side_effect=update),pytest.raises(RuntimeError):orch.trash(cid)
        row=db.get_conversation(cid);journal=orch._trash_lifecycle._path(cid)
        if failure=='rollback':
            assert journal.exists()
            with patch.object(orch,'_sync_codex_lifecycle',return_value=True):orch._trash_lifecycle.recover_all()
        assert settings.resolve_path(db.get_conversation(cid)['workspace']).exists()
        assert not journal.exists()
        assert bool(row['trashed_at']) == (failure=='commit_after')
    finally:orch._turn_finalizer_executor.shutdown(wait=True)


@pytest.mark.parametrize('channel', ['stderr', 'json'])
def test_quota_stderr_finishes_turn_and_prevents_immediate_retry(tmp_path, channel):
    import io
    class Process:
        stdout=io.StringIO(json.dumps({'type':'error','error':{'message':'Rate limit exceeded'}})+'\n' if channel=='json' else '')
        stderr=io.StringIO('ERROR AI_APICallError: Rate limit exceeded. Please try again later.\n' if channel=='stderr' else '')
        stopped=False
        def poll(self):return 1 if self.stopped else None
        def terminate(self):self.stopped=True
        def wait(self):return 1
    p=OpenCodeProvider();process=Process();p._active['c']=process;events=[]
    p._consume('c','new:c',process,events.append)
    assert process.stopped
    assert len([e for e in events if e.kind=='error'])==1
    assert events[-1].kind=='turn_completed'
    assert next(e for e in events if e.kind=='error').payload['code']=='rate_limit'
    p.command='fixture'
    with pytest.raises(ProviderRateLimited):p.send_message('d','new:d','free','medium',tmp_path,'q',events.append)


@pytest.mark.parametrize('raw,accepted', [
    ('```json\n{"supported":true,"unsupported_claims":[]}\n```', True),
    ('Resultado: {"supported":true,"unsupported_claims":[]}', True),
    ('{"supported":false,"unsupported_claims":["Sem suporte"]}', False),
    ('{"supported":"true","unsupported_claims":[]}', False),
    ('[]', False),
    ('', False),
])
def test_operational_review_parses_provider_wrappers_and_validates_shape(tmp_path, monkeypatch, raw, accepted):
    settings,db,orch,_,cid,_=fixture._orchestrator(tmp_path,'ultra')
    from vrsoft_extractor.mary.models import ModelRef
    monkeypatch.setattr(orch,'_run_ephemeral_turn',lambda *a,**kw:raw)
    try:
        issues=orch._check_operational_evidence(cid,'r',ModelRef('codex','m'),settings.root,'q',FinalDraft('Resposta',()),EvidenceBundle(QueryProfile(query='q',intents={})))
        assert (not issues) == accepted
    finally:
        orch._turn_finalizer_executor.shutdown(wait=True)


def test_operational_review_rejects_unsupported_majority(tmp_path,monkeypatch):
    settings,db,orch,_,cid,_=fixture._orchestrator(tmp_path,'ultra')
    from vrsoft_extractor.mary.models import ModelRef
    captured=[]
    def review(*args,**kwargs):
        captured.append(args[4]);return json.dumps({'supported':False,'unsupported_claims':['Confirmação pode cancelar por exceção.']})
    monkeypatch.setattr(orch,'_run_ephemeral_turn',review)
    c=EvidenceCandidate('known','code','s',0,0,'Mensagem','confirmar','java','','','throw new OperacaoCanceladaException();')
    try:
        violations=orch._check_operational_evidence(cid,'r',ModelRef('codex','m'),settings.root,'q',FinalDraft('Bug: nunca cancela.',('known',)),EvidenceBundle(QueryProfile(query='q',intents={}),candidates=(c,)))
        assert violations[0].code=='unsupported_claims'
        assert 'OperacaoCanceladaException' in captured[0]
    finally:orch._turn_finalizer_executor.shutdown(wait=True)


def test_additional_indexed_read_stays_in_selected_release(tmp_path):
    import sqlite3
    import hashlib
    database = tmp_path / 'indice/codigo/processing.sqlite'
    database.parent.mkdir(parents=True)
    path = tmp_path / 'decompiled/Child.java'
    path.parent.mkdir()
    path.write_bytes(b'class Child {\r\n void confirm() {}\r\n}')
    normalized = path.read_text(encoding='utf8')
    digest = hashlib.sha256(normalized.encode()).hexdigest()
    with sqlite3.connect(database) as con:
        con.execute('CREATE TABLE code_sources (source_key TEXT, release_id TEXT, qualified_name TEXT, output_reference TEXT, source_relative_path TEXT, source_sha256 TEXT)')
        con.executemany('INSERT INTO code_sources VALUES (?,?,?,?,?,?)', [
            ('seed','r1','Parent','decompiled','Parent.java',''),
            ('child','r1','Child','decompiled','Child.java',digest),
        ])
    c=EvidenceCandidate('code:seed','code','seed',0,0,'Parent','Parent','java','','','parent')
    e=RuntimeEvent('c','tool_event',payload={'part':{'tool':'read','state':{'status':'completed','input':{'filePath':str(path)}}}})
    got=capture_read(e,tmp_path,[c])
    assert got is not None and got.source_id=='child' and 'void confirm' in got.excerpt
    with sqlite3.connect(database) as con:
        con.execute("UPDATE code_sources SET release_id='r2' WHERE source_key='child'")
    assert capture_read(e,tmp_path,[c]) is None


def test_direct_operational_answer_uses_primary_review(tmp_path, monkeypatch):
    settings,db,orch,_,cid,_=fixture._orchestrator(tmp_path,'ultra')
    c=EvidenceCandidate('known','code','s',0,0,'Confirmar','confirmar','java','','','throw new Cancelled();')
    orch._pending_evidence_bundles[cid]=EvidenceBundle(QueryProfile(query='q',intents={}),candidates=(c,))
    monkeypatch.setattr('vrsoft_extractor.mary.orchestrator.validate_normal_response', lambda *a, **kw: ())
    monkeypatch.setattr(orch, '_run_ephemeral_turn', lambda *a, **kw: json.dumps({'supported':False,'unsupported_claims':['Cancelamento existe.']}))
    try:
        result=orch._validate_direct_response(cid,'Bug: nunca cancela.')
        assert 'Bug: nunca cancela.' not in result
    finally:
        orch._turn_finalizer_executor.shutdown(wait=True)


@pytest.mark.parametrize('supported_after_fix', [True, False])
def test_ultra_repairs_semantic_issues_before_final_rejection(tmp_path, monkeypatch, supported_after_fix):
    settings,db,orch,_,cid,events=fixture._orchestrator(tmp_path,'ultra')
    from vrsoft_extractor.mary.supervision import ResponseViolation
    problem = (ResponseViolation('unsupported_claims', 'Afirmação sem suporte.', 'Remova a afirmação.'),)
    reviews = []
    def review(*args, timeout_seconds):
        assert 0 < timeout_seconds <= 90
        reviews.append(args[5].answer_markdown)
        return problem if len(reviews) == 1 or not supported_after_fix else ()
    drafts = iter(['Sempre executa. Fato preservado.', 'Fato preservado.', 'Fato preservado.'])
    prompts = []
    def synthesis(*args, **kwargs):
        prompts.append(args[6])
        return json.dumps({'answer_markdown': next(drafts), 'used_evidence_ids': ['wiki:nf-fiscal:1']}), {}, {}
    monkeypatch.setattr(orch, '_run_buffered_main_turn', synthesis)
    monkeypatch.setattr(orch, '_check_operational_evidence', review)
    try:
        fixture._run_send(orch, cid, events)
        answer = next(r['content'] for r in db.messages(cid) if r['role'] == 'assistant')
        assert len(reviews) == (2 if supported_after_fix else 3)
        assert len(prompts) == (2 if supported_after_fix else 3)
        assert 'Afirmação sem suporte.' in prompts[1]
        assert ('Fato preservado.' in answer) == supported_after_fix
        assert 'Sempre executa.' not in answer
    finally:
        orch._turn_finalizer_executor.shutdown(wait=True)


def test_direct_review_repairs_and_rechecks_supported_content(tmp_path, monkeypatch):
    settings,db,orch,_,cid,_=fixture._orchestrator(tmp_path,'vr')
    c=EvidenceCandidate('known','wiki','s',0,0,'Pedido','Pedido','functional','','','Pedido registrado.')
    orch._pending_evidence_bundles[cid]=EvidenceBundle(QueryProfile(query='q',intents={}),candidates=(c,))
    monkeypatch.setattr('vrsoft_extractor.mary.orchestrator.validate_normal_response', lambda *a, **kw: ())
    answers=iter(['{"supported":false,"unsupported_claims":["Sempre não comprovado"]}', 'Pedido registrado.', '```json\n{"supported":true,"unsupported_claims":[]}\n```'])
    monkeypatch.setattr(orch,'_run_ephemeral_turn',lambda *a, **kw:next(answers))
    try:
        assert orch._validate_direct_response(cid,'Sempre registrado.') == 'Pedido registrado.'
    finally:
        orch._turn_finalizer_executor.shutdown(wait=True)
