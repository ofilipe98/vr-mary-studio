"""
Testes de relações verificáveis e expansão limitada (Lote L6).

Valida os requisitos de PLANO_V2_ULTRA_BUSCA_ARQUITETURA.md:
1. Extração determinística de relações a partir de markdown (links, tabelas TB_*, telas VR*).
2. Persistência e consulta de relações em SQLite com índices dedicados.
3. Expansão limitada de contexto (máximo 3 documentos e 2.000 tokens).
4. Prevenção estrita de ciclos (A -> B e B -> A).
5. Marcação transparente de 'expanded_from' e metadados da relação.
6. Degradação graciosa sem expansão quando não há relações confiáveis.
"""

from __future__ import annotations

from pathlib import Path


from vrsoft_extractor.mary.models import EvidenceCandidate, KnowledgeDocument
from vrsoft_extractor.mary.retrieval import (
    ContextExpander,
    DocumentRelation,
    RelationExtractor,
    RelationRepository,
)


class TestRelationExtraction:
    def test_extract_markdown_links_tables_and_screens(self) -> None:
        sample_md = """# Manual de Faturamento VR0101

Consulte as regras gerais em [Apuração de ICMS](/wiki/apuracao_icms.md).
Os registros são salvos na tabela TB_NFE_CABECALHO e os itens em TB_NFE_ITENS.
A tela VR0101 faz interface com a rotina VR_EXPORTADOR_SPED.
Para contingência, veja também [Contingência PDV](/wiki/pdv_contingencia.md).
"""
        relations = RelationExtractor.extract_relations("wiki/faturamento", sample_md)

        # 1. Links
        cites = [r for r in relations if r.relation_type == "cites"]
        target_ids = {r.target_id for r in cites}
        assert "wiki/apuracao_icms" in target_ids
        assert "wiki/pdv_contingencia" in target_ids

        # 2. Schema tables
        tables = [r for r in relations if r.relation_type == "schema_table"]
        table_targets = {r.target_id for r in tables}
        assert "schema:TB_NFE_CABECALHO" in table_targets
        assert "schema:TB_NFE_ITENS" in table_targets

        # 3. Screens
        screens = [r for r in relations if r.relation_type == "screen_reference"]
        screen_targets = {r.target_id for r in screens}
        assert "screen:VR0101" in screen_targets
        assert "screen:VR_EXPORTADOR_SPED" in screen_targets


class TestRelationRepository:
    def test_save_and_retrieve_outward_relations(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test_relations.db"
        repo = RelationRepository(db_path)

        relations = [
            DocumentRelation("doc-A", "doc-B", "cites", 0.95),
            DocumentRelation("doc-A", "doc-C", "schema_table", 0.85),
            DocumentRelation("doc-A", "doc-D", "screen_reference", 0.60),  # Low confidence
        ]
        repo.save_relations(relations)

        # min_confidence 0.70 should return B and C, but exclude D
        outward = repo.get_outward_relations("doc-A", min_confidence=0.70)
        assert len(outward) == 2
        targets = {r.target_id for r in outward}
        assert targets == {"doc-B", "doc-C"}


class TestBoundedContextExpansion:
    def test_expansion_respects_max_added_and_cycle_prevention(self, tmp_path: Path) -> None:
        db_path = tmp_path / "expansion.db"
        repo = RelationRepository(db_path)

        # Cycle: A -> B and B -> A, plus A -> C, A -> D, A -> E
        repo.save_relations([
            DocumentRelation("doc-A", "doc-B", "cites", 0.95),
            DocumentRelation("doc-B", "doc-A", "cites", 0.95),  # Cyclic backlink
            DocumentRelation("doc-A", "doc-C", "cites", 0.90),
            DocumentRelation("doc-A", "doc-D", "cites", 0.88),
            DocumentRelation("doc-A", "doc-E", "cites", 0.85),
        ])

        documents = {
            "doc-B": KnowledgeDocument(
                source="wiki", source_id="doc-B", source_origin="vrwiki",
                title="Doc B", url="https://vr/b", markdown="Conteúdo do documento B",
            ),
            "doc-C": KnowledgeDocument(
                source="wiki", source_id="doc-C", source_origin="vrwiki",
                title="Doc C", url="https://vr/c", markdown="Conteúdo do documento C",
            ),
            "doc-D": KnowledgeDocument(
                source="wiki", source_id="doc-D", source_origin="vrwiki",
                title="Doc D", url="https://vr/d", markdown="Conteúdo do documento D",
            ),
            "doc-E": KnowledgeDocument(
                source="wiki", source_id="doc-E", source_origin="vrwiki",
                title="Doc E", url="https://vr/e", markdown="Conteúdo do documento E",
            ),
        }

        expander = ContextExpander(
            relation_repo=repo,
            doc_resolver=lambda doc_id: documents.get(doc_id),
            max_added=3,  # Strict limit: at most 3
            max_added_tokens=2000,
        )

        primary = [
            EvidenceCandidate(
                evidence_id="doc-A",
                source="wiki",
                source_id="doc-A",
                document_id=1,
                chunk_id=1,
                title="Doc A",
                heading="",
                content_type="wiki",
                module="Fiscal",
                product="VRMaster",
                excerpt="Trecho do documento principal A",
                url="https://vr/a",
                source_origin="vrwiki",
                score=0.9,
            )
        ]

        expanded = expander.expand(primary)

        # Primary (1) + expanded (max 3) = 4 total
        assert len(expanded) == 4
        # doc-A was visited, so cycle backlink from B -> A is prevented!
        expanded_ids = [c.evidence_id for c in expanded]
        assert expanded_ids[0] == "doc-A"
        assert expanded_ids[1:] == ["doc-B", "doc-C", "doc-D"]

        # Check metadata of expanded items
        item_b = next(c for c in expanded if c.evidence_id == "doc-B")
        assert item_b.entities["expanded_from"] == ("doc-A",)
        assert item_b.entities["relation_type"] == ("cites",)
        assert "[Relacionado via Doc A]" in item_b.title

    def test_expansion_gracefully_handles_no_relations(self, tmp_path: Path) -> None:
        db_path = tmp_path / "empty_rel.db"
        repo = RelationRepository(db_path)
        expander = ContextExpander(
            relation_repo=repo,
            doc_resolver=lambda doc_id: None,
            max_added=3,
        )
        primary = [
            EvidenceCandidate(
                evidence_id="isolated",
                source="wiki",
                source_id="isolated",
                document_id=1,
                chunk_id=1,
                title="Isolado",
                heading="",
                content_type="wiki",
                module="Fiscal",
                product="VRMaster",
                excerpt="Sem relacoes",
                url="https://vr/iso",
                source_origin="vrwiki",
                score=0.8,
            )
        ]
        result = expander.expand(primary)
        assert len(result) == 1
        assert result[0].evidence_id == "isolated"
