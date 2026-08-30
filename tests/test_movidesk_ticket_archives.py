from __future__ import annotations

import json
from copy import deepcopy
import zipfile
from pathlib import Path

import pytest

from vrsoft_extractor.mary.cli import main as cli_main
from vrsoft_extractor.mary.code_analysis_benchmark import (
    audit_benchmark_intake,
    load_benchmark_suite,
    verify_benchmark_intake_manifest,
)
from vrsoft_extractor.mary.movidesk_ticket_archives import (
    MovideskTicketArchiveError,
    audit_movidesk_ticket_archives,
    build_movidesk_ticket_review_packet,
    finalize_movidesk_ticket_review,
)


def _write_ticket(
    root: Path,
    folder: str,
    ticket_number: str,
    *,
    action_role: str,
    content: str,
) -> Path:
    target = root / folder / f"movidesk-Ticket-Edit-{ticket_number}-saved.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    html = f"""
    <html><body>
      <div class="ticket-container closed">
        <div id="ticket-status-container"><span class="select2-chosen">Resolvido</span></div>
        <div id="client-container"><span class="select2-chosen">Empresa Segredo Ltda</span></div>
        <div class="owner"><span class="select2-chosen">Agente Exemplo</span></div>
        <input class="subject" value="Erro da Empresa Segredo Ltda no VRPdv">
        <div id="action-list">
          <div class="action-item public {action_role}">
            <div class="action-item-title">
              <span class="createdBy">Agente Exemplo</span>
              <span class="createdDate">10/01/2026 14:30</span>
            </div>
            <div class="action-item-content">{content}</div>
          </div>
        </div>
      </div>
    </body></html>
    """
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("index.html", html)
        archive.writestr("assets/site.css", "body {}")
    return target


def _write_source(root: Path) -> Path:
    _write_ticket(
        root,
        "N1 - Cliente",
        "2900001",
        action_role="client",
        content=(
            "Olá, Roberto. Contato pessoa@cliente.com, CPF 529.982.247-25, "
            "ticket 2900001 e IP 10.0.0.12."
        ),
    )
    _write_ticket(
        root,
        "N2 - N1",
        "2900002",
        action_role="agent",
        content="O desenvolvimento confirmou bug no código do VRPdv e ajustou a versão.",
    )
    return root


def _write_benchmark_source(root: Path) -> Path:
    for index in range(5):
        _write_ticket(
            root,
            "N2 - N1",
            str(2_910_000 + index),
            action_role="agent",
            content=(
                "O desenvolvimento confirmou bug no código do VRPdv e corrigiu "
                f"o cenário técnico {index}."
            ),
        )
    return root


def _approve_candidates(packet: dict[str, object], count: int = 5) -> None:
    candidates = packet["candidates"]
    assert isinstance(candidates, list)
    for index, candidate in enumerate(candidates[:count], start=1):
        review = candidate["review"]
        review.update(
            {
                "anonymization_approved": True,
                "eligible_for_code_benchmark": True,
                "benchmark_title": f"Falha técnica anonimizada {index}",
                "benchmark_question": (
                    "Qual causa em código explica a falha e qual correção foi aplicada?"
                ),
                "resolved_at": "2026-01-10",
                "module": "VRPdv" if index < 4 else "VRMaster",
                "target_jars": ["VRPdv.jar"],
                "known_root_cause": (
                    "Validação incorreta de estado no fluxo de emissão do documento."
                ),
                "root_cause_evidence": (
                    "A correção da classe foi implantada e reproduziu o resultado esperado."
                ),
                "expected_terms": ["validação de estado"],
                "expected_code_symbols": [f"ClasseExemplo{index}.validar"],
                "expected_citation_sources": ["VRPdv.jar"],
                "forbidden_terms": ["alterar somente o cadastro"],
            }
        )


def test_archive_audit_never_exposes_ticket_content(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "Auditoria")

    audit = audit_movidesk_ticket_archives(source)
    rendered = json.dumps(audit, ensure_ascii=False)

    assert audit["archive_count"] == 2
    assert audit["resolved_count"] == 2
    assert audit["channel_distribution"] == {"n1_client": 1, "n2_n1": 1}
    assert audit["code_evidence_candidate_count"] == 1
    assert audit["enough_confirmed_for_benchmark"] is False
    assert "Empresa Segredo" not in rendered
    assert "pessoa@cliente.com" not in rendered
    assert "2900001" not in rendered


def test_review_packet_redacts_content_and_separates_source_key(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "Auditoria")

    packet, key = build_movidesk_ticket_review_packet(source)
    rendered_packet = json.dumps(packet, ensure_ascii=False)
    rendered_key = json.dumps(key, ensure_ascii=False)

    assert packet["safe_for_model"] is False
    assert len(packet["candidates"]) == 2
    assert packet["content_fingerprint"] == key["content_fingerprint"]
    assert key["sensitive_source_key"] is True
    assert key["share_with_reviewer"] is False
    assert all(
        item["automated_redaction"]["remaining_sensitive_pattern_count"] == 0
        for item in packet["candidates"]
    )
    assert "Empresa Segredo" not in rendered_packet
    assert "Agente Exemplo" not in rendered_packet
    assert "Roberto" not in rendered_packet
    assert "pessoa@cliente.com" not in rendered_packet
    assert "529.982.247-25" not in rendered_packet
    assert "2900001" not in rendered_packet
    assert "2900001" in rendered_key
    assert all(
        item["review"]["anonymization_approved"] is False
        and item["review"]["eligible_for_code_benchmark"] is False
        for item in packet["candidates"]
    )


def test_archive_requires_one_index_html(tmp_path: Path) -> None:
    target = tmp_path / "Auditoria" / "N2 - N1" / "invalid.zip"
    target.parent.mkdir(parents=True)
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("other.html", "<html></html>")

    with pytest.raises(MovideskTicketArchiveError, match="index.html"):
        audit_movidesk_ticket_archives(target.parent.parent)


def test_cli_writes_review_and_key_without_overwriting(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "Auditoria")
    review = tmp_path / "review.json"
    key = tmp_path / "source-key.json"

    assert cli_main(["audit-movidesk-ticket-archives", str(source)]) == 0
    assert cli_main(
        [
            "prepare-movidesk-ticket-review",
            str(source),
            "--output",
            str(review),
            "--key-output",
            str(key),
        ]
    ) == 0
    assert review.exists() and key.exists()
    assert cli_main(
        [
            "prepare-movidesk-ticket-review",
            str(source),
            "--output",
            str(review),
            "--key-output",
            str(key),
        ]
    ) == 2


def test_finalize_review_builds_ready_frozen_benchmark(tmp_path: Path) -> None:
    source = _write_benchmark_source(tmp_path / "Auditoria")
    packet, key = build_movidesk_ticket_review_packet(source)
    _approve_candidates(packet)

    suite_payload, manifest = finalize_movidesk_ticket_review(
        packet,
        key,
        release_id="2026.08.30",
        anonymization_review_id="anon-review-local-001",
    )
    suite_path = tmp_path / "suite.json"
    suite_path.write_text(json.dumps(suite_payload), encoding="utf-8")
    suite = load_benchmark_suite(suite_path)

    assert len(suite.cases) == 5
    assert suite.release_id == "2026.08.30"
    assert audit_benchmark_intake(suite)["ready"] is True
    assert verify_benchmark_intake_manifest(suite, manifest)["ready"] is True
    assert manifest["source_review"]["source_key_verified"] is True
    assert len(manifest["source_review"]["selected_candidate_ids"]) == 5
    assert "actions" not in json.dumps(suite_payload)
    assert "subject" not in json.dumps(suite_payload)


def test_finalize_review_rejects_ineligible_sample_and_missing_approval(
    tmp_path: Path,
) -> None:
    source = _write_benchmark_source(tmp_path / "Auditoria")
    packet, key = build_movidesk_ticket_review_packet(source)

    with pytest.raises(MovideskTicketArchiveError, match="entre 5 e 10"):
        finalize_movidesk_ticket_review(
            packet,
            key,
            release_id="2026.08.30",
            anonymization_review_id="anon-review-local-001",
        )

    _approve_candidates(packet)
    packet["candidates"][0]["review"]["anonymization_approved"] = False
    with pytest.raises(MovideskTicketArchiveError, match="sem aprovação"):
        finalize_movidesk_ticket_review(
            packet,
            key,
            release_id="2026.08.30",
            anonymization_review_id="anon-review-local-001",
        )


def test_finalize_review_rejects_tampering_and_sensitive_manual_fields(
    tmp_path: Path,
) -> None:
    source = _write_benchmark_source(tmp_path / "Auditoria")
    packet, key = build_movidesk_ticket_review_packet(source)
    _approve_candidates(packet)

    tampered = deepcopy(packet)
    tampered["candidates"][0]["subject"] = "conteúdo alterado"
    with pytest.raises(MovideskTicketArchiveError, match="conteúdo imutável"):
        finalize_movidesk_ticket_review(
            tampered,
            key,
            release_id="2026.08.30",
            anonymization_review_id="anon-review-local-001",
        )

    packet["candidates"][0]["review"]["benchmark_question"] = (
        "Por que o erro ocorreu para contato cliente@example.com nesta rotina?"
    )
    with pytest.raises(MovideskTicketArchiveError, match="padrões sensíveis"):
        finalize_movidesk_ticket_review(
            packet,
            key,
            release_id="2026.08.30",
            anonymization_review_id="anon-review-local-001",
        )


def test_cli_finalizes_suite_and_manifest_without_overwrite(tmp_path: Path) -> None:
    source = _write_benchmark_source(tmp_path / "Auditoria")
    packet, key = build_movidesk_ticket_review_packet(source)
    _approve_candidates(packet)
    review_path = tmp_path / "review.json"
    key_path = tmp_path / "key.json"
    suite_path = tmp_path / "suite.json"
    manifest_path = tmp_path / "manifest.json"
    review_path.write_text(json.dumps(packet), encoding="utf-8")
    key_path.write_text(json.dumps(key), encoding="utf-8")
    arguments = [
        "finalize-movidesk-ticket-review",
        str(review_path),
        str(key_path),
        "--release",
        "2026.08.30",
        "--anonymization-review-id",
        "anon-review-local-001",
        "--output",
        str(suite_path),
        "--manifest-output",
        str(manifest_path),
    ]

    assert cli_main(arguments) == 0
    assert suite_path.exists() and manifest_path.exists()
    assert cli_main(arguments) == 2
