"""Independent integration and crash-boundary tests for the completed V2 paths."""
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.execution import ExecutionBudget, ResearchRepository
from vrsoft_extractor.mary.models import KnowledgeDocument
from vrsoft_extractor.mary.knowledge_router import KnowledgeRouter
from vrsoft_extractor.mary.retrieval.service import RetrievalService
from vrsoft_extractor.mary.retrieval.generations import GenerationSemanticIndex
from vrsoft_extractor.mary.retrieval.embedding_contract import DeterministicHashEmbedding


def test_real_process_exit_recovers_only_orphan_and_keeps_checkpoint(tmp_path):
    path = tmp_path / 'state.sqlite'
    script = """
import os,sys
from vrsoft_extractor.mary.execution import ResearchRepository,ExecutionBudget
r=ResearchRepository(sys.argv[1])
r.create_run('crashed','conversation',{},'request',ExecutionBudget().to_dict())
r.save_step_result('crashed','done','worker','research','Fiscal','hash','completed',output={'raw':'done'},record_attempt=True)
r.save_step_result('crashed','unknown','worker2','research','PDV','hash2','running')
os._exit(17)
"""
    result = subprocess.run([sys.executable, '-c', script, str(path)], timeout=20)
    assert result.returncode == 17
    repo = ResearchRepository(path)
    assert repo.get_run('crashed')['status'] == 'interrupted'
    assert repo.find_reusable_step('hash', run_id='crashed')['output'] == {'raw':'done'}
    unknown = next(s for s in repo.get_steps_for_run('crashed') if s['stage_id']=='unknown')
    assert unknown['status']=='interrupted' and 'desconhecida' in unknown['error']
    repo.create_run('alive','conversation',{},'request',ExecutionBudget().to_dict())
    assert ResearchRepository(path).get_run('alive')['status']=='running'


def test_simultaneous_resume_has_one_owner_and_old_owner_cannot_write(tmp_path):
    path = tmp_path/'claims.sqlite'
    original = ResearchRepository(path)
    original.create_run('r','c',{},'request',ExecutionBudget().to_dict())
    original.update_run_status('r','cancelled')
    contenders=[ResearchRepository(path),ResearchRepository(path)]
    def claim(repo):
        try:
            return repo.claim_resume('r','c',execution_id=42)
        except ValueError:
            return None
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(claim,contenders))
    assert sum(r is not None for r in results)==1
    assert original.get_run('r')['execution_id']==42
    with pytest.raises(RuntimeError):
        original.update_run_status('r','failed')


def test_startup_preserves_conversation_with_live_research_owner(tmp_path):
    db = MaryDatabase(tmp_path / 'live.sqlite', root=tmp_path)
    live = db.create_conversation('Live', 'codex', 'model', tmp_path)
    orphan = db.create_conversation('Orphan', 'codex', 'model', tmp_path)
    db.begin_user_turn(live, 'research')
    db.begin_user_turn(orphan, 'old turn')
    repo = ResearchRepository(db.path)
    repo.create_run('live', live, {}, 'research', ExecutionBudget().to_dict())
    assert db.recover_interrupted_conversations() == [orphan]
    assert db.get_conversation(live)['status'] == 'running'
    assert repo.get_run('live')['status'] == 'running'


def test_caller_relations_reject_wrong_release_stale_and_unresolved(tmp_path, monkeypatch):
    from vrsoft_extractor.mary.retrieval import code_relations
    base = dict(release_hash='manifest', freshness='fresh', resolution='syntactic',
                source_sha256='sourcehash', qualified_name='Example.run', line_start=10,
                excerpt='save(item);', confidence=.6, citation='Example.java:10')
    rows = [dict(base, release_hash='old'), dict(base, freshness='stale'),
            dict(base, resolution='ambiguous'), dict(base, source_sha256=''), base, base]
    monkeypatch.setattr(code_relations.JavaCodeIndex, 'callers', lambda *a, **k: rows)
    results = code_relations.caller_evidence(tmp_path, ['save'], release_id='r2', manifest_hash='manifest')
    assert len(results) == 1
    assert results[0].content_type == 'java_syntactic_relation'
    assert results[0].entities['source_sha256'] == ('sourcehash',)
    assert not code_relations.caller_evidence(tmp_path, ['save'], release_id='r2', manifest_hash='manifest', max_chars=2)


def test_claude_streams_large_unicode_prompt_through_stdin(tmp_path, monkeypatch):
    import hashlib
    import threading
    from vrsoft_extractor.mary.provider_adapters import claude
    provider = claude.ClaudeProvider()
    provider.command = sys.executable
    prompt = ('ação & echo NÃO_EXECUTAR | %PATH% "$(literal)"\n' * 3000)
    expected = hashlib.sha256(prompt.encode()).hexdigest()
    real_popen = subprocess.Popen
    script = "import sys,json,hashlib; data=sys.stdin.buffer.read(); print(json.dumps({'type':'result','result':hashlib.sha256(data).hexdigest()}))"
    def launch(command, **kwargs):
        assert prompt not in command and len(' '.join(command)) < 4096
        assert kwargs['stdin'] == subprocess.PIPE
        return real_popen([sys.executable, '-c', script], **kwargs)
    monkeypatch.setattr(claude.subprocess, 'Popen', launch)
    done, events = threading.Event(), []
    def callback(event):
        events.append(event)
        if event.kind == 'turn_completed':
            done.set()
    try:
        provider.send_message('large', '', 'default', 'low', tmp_path, prompt, callback)
        assert done.wait(15)
        assert not [e for e in events if e.kind == 'error']
        assert expected in ''.join(e.text for e in events if e.kind == 'assistant_delta')
    finally:
        provider.close()


def test_publication_message_citations_and_ledger_commit_together(tmp_path):
    db=MaryDatabase(tmp_path/'database.sqlite',root=tmp_path)
    cid=db.create_conversation('codex','model','medium',str(tmp_path))
    # create_conversation returns a local id, never a native provider session id.
    execution=db.begin_user_turn(cid,'request')
    repo=ResearchRepository(db.path)
    repo.create_run('r',cid,{},'request',ExecutionBudget().to_dict())
    repo.set_context('r',{},execution)
    doc_id,_=db.upsert_document(KnowledgeDocument('wiki','source','Title','',markdown='Evidence'))
    kwargs=dict(execution_id=execution,execution_ordinal=1,research_run_id='r',research_citations=[{'document_id':doc_id,'excerpt':'Evidence'}])
    first=db.upsert_assistant_message(cid,'answer',**kwargs)
    second=db.upsert_assistant_message(cid,'answer',**kwargs)
    assert first==second==repo.get_run('r')['publication_message_id']
    assert len([m for m in db.messages(cid) if m['role']=='assistant'])==1
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM source_citations WHERE message_id=?',(first,)).fetchone()[0]==1
    with pytest.raises(RuntimeError):
        db.upsert_assistant_message(cid,'must rollback',execution_id=execution,execution_ordinal=2,research_run_id='missing')
    assert len([m for m in db.messages(cid) if m['role']=='assistant'])==1


def row(doc_id, text, **kwargs):
    return {'id':int(doc_id), 'source':'wiki','source_id':str(doc_id),'source_origin':'vrwiki','module':'Fiscal','product':'ERP',
            'revision':'r2','status':'active','review_status':'approved','title':'Document','markdown':text,**kwargs}


def test_generations_fail_without_exposing_partial_update_and_delete_stale(tmp_path):
    backend=DeterministicHashEmbedding()
    index=GenerationSemanticIndex(tmp_path/'vectors.sqlite',backend)
    index.rebuild([row(1,'invoice alpha'),row(2,'sale beta')])
    previous=index.search('invoice',limit=10)
    def fail(text):
        raise RuntimeError('model unavailable')
    original=backend.embed_text
    backend.embed_text=fail
    with pytest.raises(RuntimeError):
        index.rebuild([row(1,'changed')])
    backend.embed_text=original
    assert [r['doc_id'] for r in index.search('invoice',limit=10)]==[r['doc_id'] for r in previous]
    result=index.rebuild([row(1,'invoice alpha')])
    assert result['computed']==0 and result['reused']==1
    assert {r['doc_id'] for r in index.search('sale',limit=10)}=={'wiki:1'}


def test_vector_scope_filters_before_top_k(tmp_path):
    index=GenerationSemanticIndex(tmp_path/'vectors.sqlite',DeterministicHashEmbedding())
    index.rebuild([row(1,'invoice'),row(2,'invoice',revision='r1'),row(3,'invoice',source_origin='hidden'),row(4,'invoice',product='OTHER')])
    found=index.search('invoice',limit=1,source='wiki',origins=('vrwiki',),revision='r2',product='ERP')
    assert [r['doc_id'] for r in found]==['wiki:1']


def test_relation_pipeline_uses_verified_links_and_invalidates_removed_link(tmp_path):
    db=MaryDatabase(tmp_path/'knowledge.sqlite',root=tmp_path)
    for source_id, text in [('first','See [next](wiki:next).'),('next','Detailed procedure.'),('homonym','Mentions TB_EXAMPLE without a link.')]:
        db.upsert_document(KnowledgeDocument('wiki',source_id,source_id,'',markdown=text,module='Fiscal',review_status='approved'))
    router=KnowledgeRouter(db,tmp_path)
    router._ready=True
    service=RetrievalService(router)
    assert service.rebuild_relations()['relations']==1
    rel=service.relation_repository.get_outward_relations('wiki:first')[0]
    assert rel.metadata['verified'] and rel.metadata['source_hash'] and rel.metadata['target_document_id']
    db.upsert_document(KnowledgeDocument('wiki','first','first','',markdown='Link removed.',module='Fiscal',review_status='approved'))
    assert service.rebuild_relations()['relations']==0


def test_semantic_missing_assets_never_downloads_and_falls_back(tmp_path,monkeypatch):
    import urllib.request
    def forbidden(*args,**kwargs):
        pytest.fail('query attempted a download')
    monkeypatch.setattr(urllib.request,'urlopen',forbidden)
    db=MaryDatabase(tmp_path/'knowledge.sqlite',root=tmp_path)
    db.upsert_document(KnowledgeDocument('wiki','tax','ICMS','',markdown='ICMS fiscal.',module='Fiscal',review_status='approved'))
    router=KnowledgeRouter(db,tmp_path)
    router._ready=True
    service=RetrievalService(router)
    service.configure(mode='hybrid')
    result=service.route('ICMS')
    assert result.candidates
    assert any('Busca textual' in w for w in result.warnings)


def test_textual_scope_excludes_other_release_before_limit(tmp_path):
    db=MaryDatabase(tmp_path/'knowledge.sqlite',root=tmp_path)
    for i in range(20):
        db.upsert_document(KnowledgeDocument('wiki',str(i),'ICMS','',markdown='ICMS fiscal.',module='Fiscal',review_status='approved',revision='r2' if i==19 else 'r1'))
    assert [r['source_id'] for r in db.search('ICMS',limit=1,revision='r2')]==['19']
    assert {r['source_id'] for r in db.search_chunks('ICMS',limit=1,revision='r2')}=={'19'}
