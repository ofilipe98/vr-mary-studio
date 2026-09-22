"""Behavioral regressions from the independent V2 audit, with isolated data."""
import sqlite3

import pytest

from vrsoft_extractor.mary.execution import ExecutionBudget, ExecutionContext, ExecutionCancelledError
from vrsoft_extractor.mary.execution.budget import CallReservationError
from vrsoft_extractor.mary.execution.repository import ResearchRepository
from vrsoft_extractor.mary.retrieval.embedding_contract import EmbeddingBackend, FallbackEmbeddingBackend
from vrsoft_extractor.mary.retrieval.semantic_index import SemanticIndex
from vrsoft_extractor.mary.retrieval.hybrid_search import reciprocal_rank_fusion
from vrsoft_extractor.mary.retrieval.benchmark import ndcg_at_k
from vrsoft_extractor.mary.retrieval.relations import ContextExpander, DocumentRelation, RelationRepository
from vrsoft_extractor.mary.models import EvidenceCandidate, KnowledgeDocument


def test_context_legacy_cancel_flag_stops_execution(tmp_path):
    context = ExecutionContext('c', 'r', tmp_path, cancelled=True)
    with pytest.raises(ExecutionCancelledError):
        context.check_cancelled()


def test_budget_parallel_limit_does_not_spend_a_rejected_call():
    budget = ExecutionBudget(max_calls=6, max_parallel=1)
    budget.acquire_call()
    with pytest.raises(CallReservationError):
        budget.acquire_call()
    assert budget.calls_made == 1
    budget.release_call()
    budget.acquire_call()
    assert budget.calls_made == 2


def test_empty_replacement_removes_old_chunks(tmp_path):
    index = SemanticIndex(tmp_path / 'vectors.db')
    index.index_document('doc', 'Uma regra fiscal antiga.')
    index.index_document('doc', '')
    assert index.search('regra fiscal') == []


class BrokenModel(EmbeddingBackend):
    dimension = 128
    model_name = 'different-vector-space'

    def embed_text(self, text):
        raise RuntimeError('model unavailable')


def test_failing_model_does_not_silently_switch_vector_spaces():
    backend = FallbackEmbeddingBackend(primary=BrokenModel())
    with pytest.raises(RuntimeError, match='model unavailable'):
        backend.embed_text('fiscal')


def test_rrf_does_not_reward_duplicate_ids_in_one_lane():
    assert reciprocal_rank_fusion(['a', 'a', 'b'], []) == reciprocal_rank_fusion(['a', 'b'], [])


def test_ndcg_cannot_exceed_one_with_duplicate_results():
    assert ndcg_at_k(['a', 'a', 'a'], {'a': 1}) <= 1.0


def test_upsert_replaces_input_hash(tmp_path):
    repo = ResearchRepository(tmp_path / 'runs.db')
    repo.create_run('r', 'c', {}, 'question', {})
    for h, value in [('old', 'old answer'), ('new', 'new answer')]:
        repo.save_step_result('r', 's', 'w', 'research', 'Fiscal', h, 'completed', output={'raw': value})
    assert repo.get_steps_for_run('r')[0]['input_hash'] == 'new'
    assert repo.find_reusable_step('old', run_id='r') is None


def test_reuse_is_bound_to_requested_run_and_verified_output(tmp_path):
    repo = ResearchRepository(tmp_path / 'runs.db')
    repo.create_run('private', 'alice', {}, 'private question', {})
    repo.create_run('other', 'bob', {}, 'other question', {})
    repo.save_step_result('private', 's', 'w', 'research', 'Fiscal', 'same', 'completed', output={'raw': 'secret'})
    assert repo.find_reusable_step('same', run_id='other') is None
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute("UPDATE research_steps SET output_json=?", ('{"raw":"tampered"}',))
    assert repo.find_reusable_step('same', run_id='private') is None


def test_relation_metadata_survives_database_roundtrip(tmp_path):
    repo = RelationRepository(tmp_path / 'relations.db')
    relation = DocumentRelation('source', 'target', 'cites', metadata={'source_hash': 'hash', 'excerpt': '[link](target)'})
    repo.save_relations([relation])
    assert repo.get_outward_relations('source')[0].metadata == relation.metadata


def test_first_expansion_also_respects_zero_budget(tmp_path):
    repo = RelationRepository(tmp_path / 'relations.db')
    repo.save_relations([DocumentRelation('a', 'b', 'cites')])
    candidate = EvidenceCandidate('a', 'wiki', 'a', 1, 0, 'A', '', 'wiki', 'Fiscal', '', 'A')
    doc = KnowledgeDocument('wiki', 'b', 'B', 'https://example.invalid/b', markdown='A large related document')
    expander = ContextExpander(repo, lambda _: doc, max_added_tokens=0)
    assert expander.expand([candidate]) == [candidate]


def test_portable_sanitization_removes_private_research(tmp_path):
    from vrsoft_extractor.mary.db import MaryDatabase
    from vrsoft_extractor.mary.portable_export import _sanitize_portable_database
    db = MaryDatabase(tmp_path / 'portable.db')
    repo = ResearchRepository(db.path)
    repo.create_run('run', 'conversation', {}, 'private customer prompt', {})
    repo.save_step_result('run', 's', 'w', 'research', 'Fiscal', 'hash', 'completed', output={'raw': 'private answer'})
    repo.record_step_attempt('run:s', 1, 'completed', output={'raw': 'private answer'})
    relations = RelationRepository(db.path)
    relations.save_relations([DocumentRelation('private-document', 'other', 'cites')])
    _sanitize_portable_database(db)
    with sqlite3.connect(db.path) as conn:
        for table in ('research_step_attempts', 'research_steps', 'research_runs', 'document_relations'):
            assert conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0


def test_purge_removes_only_checkpoint_of_deleted_conversation(tmp_path):
    from vrsoft_extractor.mary.db import MaryDatabase
    db = MaryDatabase(tmp_path / 'purge.db')
    repo = ResearchRepository(db.path)
    for cid in ('delete', 'keep'):
        repo.create_run(cid, cid, {}, 'private prompt', {})
        repo.save_step_result(cid, 's', 'w', 'research', 'Fiscal', 'hash', 'completed', output={'raw': cid})
        repo.record_step_attempt(cid + ':s', 1, 'completed', output={'raw': cid})
    db.purge_conversation('delete')
    assert repo.get_run('delete') is None
    assert repo.get_steps_for_run('delete') == []
    assert repo.get_attempts_for_step('delete:s') == []
    assert repo.get_run('keep') is not None


def test_resume_budget_preserves_limits_usage_and_active_time():
    now = [100.0]
    budget = ExecutionBudget(max_calls=10, max_active_seconds=100, max_retries_per_worker=1, token_limit=500, clock=lambda: now[0])
    budget.acquire_call()
    budget.release_call(tokens_used=100)
    now[0] += 25
    snapshot = budget.to_dict()
    now[0] += 1000  # Paused wall time is not active execution time.
    restored = ExecutionBudget.from_snapshot(snapshot, clock=lambda: now[0])
    assert restored.remaining_calls() == 9
    assert restored.time_remaining() == 75
    assert restored.tokens.real == 100
    assert restored.token_limit == 500
    assert restored.max_retries_per_worker == 1


def test_long_unbroken_text_is_chunked_with_a_hard_limit():
    from vrsoft_extractor.mary.retrieval.semantic_index import chunk_text
    chunks = chunk_text('a' * 2001, max_chunk_chars=100)
    assert len(chunks) > 20
    assert max(map(len, chunks)) <= 100


def test_cancelled_completed_callback_does_not_interrupt_a_later_turn():
    from vrsoft_extractor.mary.execution import CancellationToken
    token = CancellationToken()
    interrupted = []
    unregister = token.register_callback(lambda: interrupted.append(True))
    unregister()
    token.cancel()
    assert interrupted == []


def test_retrieval_resolver_preserves_source_identity_and_origin_permissions(tmp_path):
    from vrsoft_extractor.mary.db import MaryDatabase
    from vrsoft_extractor.mary.knowledge_router import KnowledgeRouter
    from vrsoft_extractor.mary.retrieval import RetrievalService
    db = MaryDatabase(tmp_path / 'knowledge.db')
    for source in ('wiki', 'kb'):
        db.upsert_document(KnowledgeDocument(source, 'shared-id', source, 'https://example.invalid', markdown='text', module='Fiscal'))
    service = RetrievalService(KnowledgeRouter(db, tmp_path, disabled_origins=('movidesk',)))
    assert service.resolve_document('shared-id') is None
    assert service.resolve_document('wiki:shared-id').source == 'wiki'
    assert service.resolve_document('kb:shared-id') is None


def test_live_adapter_cancellation_releases_the_research_session(tmp_path):
    """Exercise the actual orchestrator adapter loop with a controlled provider."""
    import threading
    import test_mary_research_fanout as fixture
    from vrsoft_extractor.mary.db import MaryDatabase
    from vrsoft_extractor.mary.orchestrator import ChatOrchestrator
    from vrsoft_extractor.mary.models import ModelRef

    started = threading.Event()
    interrupted = []

    class WaitingProvider:
        def __init__(self):
            self.lock = threading.Lock()
            self._active_ids: set[str] = set()

        def available(self):
            return True

        def start_conversation(self, conversation_id, model, effort, workspace, options=None):
            with self.lock:
                self._active_ids.add(conversation_id)
            return f"native:{conversation_id}"

        def release_conversation(self, *args, **kwargs):
            local = str(kwargs.get("local_id") or (args[0] if args else ""))
            with self.lock:
                self._active_ids.discard(local)

        def close(self):
            pass

        def send_message(self, conversation_id, *args, **kwargs):
            started.set()  # A real asynchronous adapter can remain silent until interruption.

        def interrupt(self, conversation_id):
            interrupted.append(conversation_id)

    settings = fixture._settings(tmp_path)
    db = MaryDatabase(settings.database_path, root=settings.root)
    orch = ChatOrchestrator(settings, db)
    provider = WaitingProvider()
    orch.providers = {'codex': provider}
    cid = orch.new_conversation('codex', 'sol', defer_provider_start=True)
    context = ExecutionContext(cid, 'run', settings.work_dir)
    orch._research_contexts['run'] = context
    orch._active_orchestration_runs[cid] = 'run'
    errors = []

    def run():
        try:
            orch._run_ephemeral_turn(cid, 'run', 'worker', ModelRef('codex', 'sol'), 'prompt', settings.work_dir, 'medium', timeout_seconds=10)
        except ExecutionCancelledError as exc:
            errors.append(exc)

    thread = threading.Thread(target=run)
    try:
        thread.start()
        assert started.wait(2)
        orch.interrupt(cid)
        thread.join(2)
        assert not thread.is_alive()
        assert len(errors) == 1
        assert any(':vr:run:worker:' in item for item in interrupted)
        assert not provider._active_ids
        assert cid not in orch._active_agent_runs
    finally:
        context.cancellation.cancel()
        thread.join(2)
        orch.close()
