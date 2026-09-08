"""Evaluate the production evidence router on the frozen synthetic corpus."""
import json
import statistics
import time
from pathlib import Path
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.knowledge_router import KnowledgeRouter
from vrsoft_extractor.mary.retrieval.service import RetrievalService
from vrsoft_extractor.mary.retrieval.local_neural import LocalOnnxEmbedding
from vrsoft_extractor.mary.retrieval.generations import GenerationSemanticIndex

root = Path('reports/v2/conclusao/model-lab').resolve()
data = json.loads(Path('tests/fixtures/v2_retrieval_corpus.json').read_text(encoding='utf-8'))
db = MaryDatabase(root/'indice'/'benchmark.sqlite', root=root)
router = KnowledgeRouter(db, root, total_limit=10)
router._ready = True
service = RetrievalService(router)
report = {}
for mode in ('textual', 'hybrid'):
    service.configure(mode=mode, model='minilm')
    if mode == 'hybrid':
        service._neural = GenerationSemanticIndex(root/'indice'/'production-benchmark.sqlite', LocalOnnxEmbedding(root, 'minilm'))
        service.reindex()
    results = []
    for q in data['queries']:
        started = time.perf_counter()
        bundle = service.route(q['text'], revision=q['revision'])
        ranked = list(dict.fromkeys(f'{c.source}:{c.source_id}' for c in bundle.candidates))[:10]
        results.append({**q, 'ranked': ranked, 'milliseconds': (time.perf_counter()-started)*1000,
            'warnings': bundle.warnings, 'origins': list(dict.fromkeys(c.source_origin for c in bundle.candidates))})
    evaluation = [q for q in results if q['split'] == 'evaluation' and q['relevant']]
    paraphrases = [q for q in evaluation if q['kind'] == 'paraphrase']
    times = sorted(q['milliseconds'] for q in results)
    def metrics(rows):
        return {'recall10': statistics.mean(bool(set(q['ranked']) & set(q['relevant'])) for q in rows),
            'mrr': statistics.mean(next((1/(i+1) for i, k in enumerate(q['ranked']) if k in q['relevant']), 0) for q in rows)}
    report[mode] = {'evaluation': metrics(evaluation), 'paraphrases': metrics(paraphrases),
        'p50_ms': statistics.median(times), 'p95_ms': times[int(.95*(len(times)-1))],
        'exact_preserved': all(set(q['ranked']) & set(q['relevant']) for q in evaluation if q['kind'] == 'exact'),
        'no_answer_candidates': sum(bool(q['ranked']) for q in results if q['kind'] == 'no_answer'),
        'release_isolation': all(not any(':old-' in k for k in q['ranked']) for q in results), 'results': results}
    print(mode, {k:v for k,v in report[mode].items() if k != 'results'}, flush=True)
    Path('reports/v2/conclusao/production-benchmark.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
