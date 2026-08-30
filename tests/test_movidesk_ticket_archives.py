from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from vrsoft_extractor.mary.cli import main as cli_main
from vrsoft_extractor.mary.movidesk_ticket_archives import (
    MovideskTicketArchiveError,
    audit_movidesk_ticket_archives,
    build_movidesk_ticket_review_packet,
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
