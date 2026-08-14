from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.paths import resolve_portable_path, to_portable_path
from vrsoft_extractor.mary.portable_export import (
    audit_portable_project,
    export_portable_project,
)
from vrsoft_extractor.mary.portable_project import (
    MANAGED_MARKER,
    ensure_portable_project,
)
from vrsoft_extractor.mary.workspace import (
    CONVERSATION_MANAGED_MARKER,
    ensure_conversation_workspace,
)


def test_ensure_portable_project_backs_up_full_agents_and_is_idempotent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "VRProject"
    root.mkdir()
    legacy = "# Fluxo Mary\n\nContrato completo da Mary e dos especialistas.\n"
    (root / "AGENTS.md").write_text(legacy, encoding="utf-8")

    first = ensure_portable_project(root)
    second = ensure_portable_project(root)

    assert "AGENTS.md" in first.written
    assert (root / "agentes" / "AGENTS.md").read_text(encoding="utf-8") == legacy
    assert MANAGED_MARKER in (root / "AGENTS.md").read_text(encoding="utf-8")
    assert MANAGED_MARKER in (root / ".codex" / "config.toml").read_text(
        encoding="utf-8"
    )
    assert "max_threads = 4" in (root / ".codex" / "config.toml").read_text(
        encoding="utf-8"
    )
    assert (root / ".codex" / "agents" / "fisco.toml").is_file()
    assert (root / ".codex" / "agents" / "dba.toml").is_file()
    assert (root / "tools" / "vr-search.ps1").is_file()
    assert (root / "Abrir-VR-no-Codex.cmd").is_file()
    assert (root / "TrabalhoVR").is_dir()
    assert not (root / "tools" / "mary-search.ps1").exists()
    assert not (root / "Abrir-Mary-no-Codex.cmd").exists()
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    readme = (root / "README-CODEX.md").read_text(encoding="utf-8")
    assert "ativa o fluxo VR automaticamente" in agents
    assert "prefixo `VR:` é aceito, mas opcional" in agents
    assert "Mary" not in agents
    assert "Mary" not in readme
    assert "Modo multiagente real do Codex indisponível" not in agents
    assert "tente delegar o papel a um subagente" in agents
    assert not second.preserved


def test_conversation_workspace_repairs_legacy_files_and_preserves_user_files(
    tmp_path: Path,
) -> None:
    root = tmp_path / "VRProject"
    legacy = root / "TrabalhoMary" / "legacy"
    legacy.mkdir(parents=True)
    (legacy / "AGENTS.md").write_text(
        "# Workspace de conversa Mary\n\nInstruções principais: `../../AGENTS.md`.\n",
        encoding="utf-8",
    )

    ensure_conversation_workspace(legacy)

    assert CONVERSATION_MANAGED_MARKER in (legacy / "AGENTS.md").read_text(
        encoding="utf-8"
    )
    assert "O aplicativo fornece o contexto" in (legacy / "AGENTS.md").read_text(
        encoding="utf-8"
    )
    assert (legacy / "tools" / "vr-search.ps1").is_file()

    custom = root / "TrabalhoMary" / "custom"
    tools = custom / "tools"
    tools.mkdir(parents=True)
    (custom / "AGENTS.md").write_text("# Regras próprias\n", encoding="utf-8")
    (tools / "mary-search.ps1").write_text("# script próprio\n", encoding="utf-8")

    ensure_conversation_workspace(custom)

    assert (custom / "AGENTS.md").read_text(encoding="utf-8") == "# Regras próprias\n"
    assert (tools / "mary-search.ps1").read_text(encoding="utf-8") == "# script próprio\n"


def test_ensure_portable_project_preserves_user_owned_codex_config(tmp_path: Path) -> None:
    root = tmp_path / "VRProject"
    config = root / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('model = "custom"\n', encoding="utf-8")

    result = ensure_portable_project(root)

    assert ".codex/config.toml" in result.preserved
    assert config.read_text(encoding="utf-8") == 'model = "custom"\n'


def test_paths_relocate_old_machine_values(tmp_path: Path) -> None:
    root = (tmp_path / "VRProject").resolve()
    stale = r"D:\Codex\Projetos\VR_Mary_V2\conhecimento\PDV\KB\pinpad.md"

    portable = to_portable_path(root, stale)

    assert portable == "conhecimento/PDV/KB/pinpad.md"
    assert resolve_portable_path(root, stale) == root / "conhecimento" / "PDV" / "KB" / "pinpad.md"


def test_database_migrates_mary_owned_paths_to_relative(tmp_path: Path) -> None:
    root = tmp_path / "VRProject"
    database_path = root / "indice" / "conhecimento.sqlite"
    database = MaryDatabase(database_path)
    with database.connect() as connection:
        connection.execute(
            """INSERT INTO documents
               (source,source_id,title,url,module,synced_at,content_hash,local_path,assets_json)
               VALUES('kb','1','Pinpad','https://example.test','PDV','now','hash',?,?)""",
            (
                r"D:\Old\VR_Mary_V2\conhecimento\PDV\KB\pinpad.md",
                json.dumps([r"D:\Old\VR_Mary_V2\assets\kb\pinpad.png"]),
            ),
        )

    migrated = MaryDatabase(database_path, root=root)
    row = migrated.get_document("kb", "1")

    assert row is not None
    assert row["local_path"] == "conhecimento/PDV/KB/pinpad.md"
    assert json.loads(row["assets_json"]) == ["assets/kb/pinpad.png"]
    assert (root / ".state" / "backups" / "conhecimento-pre-portable.sqlite").is_file()


def test_export_portable_excludes_secrets_and_full_videos(tmp_path: Path) -> None:
    source = tmp_path / "SourceVR"
    destination = tmp_path / "PortableVR"
    database = MaryDatabase(source / "indice" / "conhecimento.sqlite")
    article = source / "conhecimento" / "PDV" / "KB" / "pinpad.md"
    article.parent.mkdir(parents=True)
    article.write_text(
        "Imagem: D:\\Old\\VR_Mary_V2\\assets\\kb\\pinpad.png\n",
        encoding="utf-8",
    )
    with database.connect() as connection:
        connection.execute(
            """INSERT INTO documents
               (source,source_id,title,url,module,review_status,synced_at,content_hash,
                local_path,assets_json)
               VALUES('kb','289782','Pinpad','https://example.test','PDV','approved',
                      'now','hash',?,?)""",
            (
                str(article),
                json.dumps([str(source / "assets" / "kb" / "pinpad.png")]),
            ),
        )
    state = source / ".state"
    state.mkdir()
    (state / "movidesk.json").write_text("secret", encoding="utf-8")
    (source / ".env").write_text("MOVIDESK_PASSWORD=secret", encoding="utf-8")
    video = source / "videos" / "course.mp4"
    video.parent.mkdir()
    video.write_bytes(b"video")
    (source / "videos" / "inventory.json").write_text("{}", encoding="utf-8")
    private_workspace = source / "TrabalhoVR" / "private-chat"
    private_workspace.mkdir(parents=True)
    (private_workspace / "segredo.txt").write_text(
        "histórico privado", encoding="utf-8"
    )
    conversation_id = database.create_conversation(
        "Conversa privada", "codex", "gpt-test", private_workspace
    )
    database.add_message(conversation_id, "user", "conteúdo privado")
    inactive = source / "conhecimento" / "PDV" / "KB" / "obsoleto.md"
    inactive.write_text("conteúdo removido", encoding="utf-8")
    with database.connect() as connection:
        connection.execute(
            """INSERT INTO documents
               (source,source_id,title,url,module,review_status,status,synced_at,
                content_hash,local_path)
               VALUES('kb','old','Obsoleto','https://example.test/old','PDV',
                      'approved','inactive','now','old-hash',?)""",
            (str(inactive),),
        )

    result = export_portable_project(source, destination)

    assert result.manifest.is_file()
    assert not (destination / ".state").exists()
    assert not (destination / ".env").exists()
    assert not (destination / "videos" / "course.mp4").exists()
    assert (destination / "videos" / "inventory.json").is_file()
    assert (destination / "TrabalhoVR").is_dir()
    assert not (destination / "TrabalhoVR" / "private-chat").exists()
    assert not (destination / "conhecimento" / "PDV" / "KB" / "obsoleto.md").exists()
    assert "assets/kb/pinpad.png" in (
        destination / "conhecimento" / "PDV" / "KB" / "pinpad.md"
    ).read_text(encoding="utf-8")
    migrated = MaryDatabase(
        destination / "indice" / "conhecimento.sqlite", root=destination
    ).get_document("kb", "289782")
    assert migrated is not None
    assert migrated["local_path"] == "conhecimento/PDV/KB/pinpad.md"
    portable_database = MaryDatabase(
        destination / "indice" / "conhecimento.sqlite", root=destination
    )
    with portable_database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM conversations").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM documents").fetchone()[0] == 1
    assert (private_workspace / "segredo.txt").is_file()
    assert database.get_conversation(conversation_id) is not None
    audit = audit_portable_project(destination)
    assert audit["ready"] is True
    assert audit["absolute_database_paths"] == 0


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell ausente")
def test_portable_search_runs_without_python(tmp_path: Path) -> None:
    root = tmp_path / "VRProject"
    ensure_portable_project(root)
    article = root / "conhecimento" / "PDV" / "KB" / "pinpad.md"
    article.parent.mkdir(parents=True)
    article.write_text("Erro ao finalizar venda com TEF e pinpad.", encoding="utf-8")
    catalog = root / "indice" / "catalogo.jsonl"
    catalog.parent.mkdir(parents=True)
    catalog.write_text(
        json.dumps(
            {
                "source": "kb",
                "source_id": "289782",
                "title": "Erro ao finalizar venda com TEF",
                "module": "PDV",
                "review_status": "approved",
                "status": "active",
                "local_path": "conhecimento/PDV/KB/pinpad.md",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(root / "tools" / "vr-search.ps1"),
            "-Query",
            "pinpad TEF",
            "-Limit",
            "5",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
    )
    result = json.loads(completed.stdout)

    assert result["total"] == 1
    assert result["results"][0]["source_id"] == "289782"
    assert result["results"][0]["local_path"] == "conhecimento/PDV/KB/pinpad.md"


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell ausente")
def test_portable_search_resolves_function_102_without_fiscal_results(tmp_path: Path) -> None:
    root = tmp_path / "VRProject"
    ensure_portable_project(root)
    entries = [
        {
            "source": "wiki",
            "source_id": "3742",
            "title": "Funcao 102",
            "module": "PDV",
            "url": "https://wiki.example/index.php?title=Funcao_102",
            "local_path": "conhecimento/PDV/Wiki/funcao-102--3742.md",
            "content": (
                "Função responsável por identificar um operador para o caixa. "
                "Status FECHADO PARCIAL. Tecla de atalho O."
            ),
        },
        {
            "source": "wiki",
            "source_id": "4495",
            "title": "MAPA DE FUNCOES",
            "module": "PDV",
            "url": "https://wiki.example/index.php?title=MAPA_DE_FUNCOES",
            "local_path": "conhecimento/PDV/Wiki/mapa-de-funcoes--4495.md",
            "content": (
                "[Funcao 102 - Entrada Operador]"
                "(https://wiki.example/index.php?title=Funcao_102)"
            ),
        },
        {
            "source": "kb",
            "source_id": "fiscal",
            "title": "Manual de cadastro de entrada fiscal",
            "module": "Fiscal",
            "url": "https://kb.example/fiscal",
            "local_path": "conhecimento/Fiscal/KB/manual-fiscal.md",
            "content": "Função de entrada do operador em cadastro de nota fiscal.",
        },
    ]
    entries.extend(
        {
            "source": "wiki",
            "source_id": f"pdv-{index}",
            "title": f"Procedimento PDV {index}",
            "module": "PDV",
            "url": f"https://wiki.example/pdv-{index}",
            "local_path": f"conhecimento/PDV/Wiki/procedimento-{index}.md",
            "content": "Consulte a função para entrada do operador no PDV.",
        }
        for index in range(7)
    )
    catalog_lines = []
    for entry in entries:
        path = root / entry["local_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(entry.pop("content"), encoding="utf-8")
        catalog_lines.append(
            json.dumps(
                {
                    **entry,
                    "review_status": "approved",
                    "status": "active",
                },
                ensure_ascii=False,
            )
        )
    catalog = root / "indice" / "catalogo.jsonl"
    catalog.parent.mkdir(parents=True, exist_ok=True)
    catalog.write_text("\n".join(catalog_lines) + "\n", encoding="utf-8")

    def run(query: str) -> dict:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(root / "tools" / "vr-search.ps1"),
                "-Query",
                query,
                "-Limit",
                "8",
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8-sig",
        )
        return json.loads(completed.stdout)

    plain = run("Qual a função de entrada do operador?")
    prefixed = run("Mary: Qual a função de entrada do operador?")

    assert plain["results"][0]["source_id"] == "3742"
    assert plain["results"][0]["resolved_from"] == "MAPA DE FUNCOES"
    assert plain["results"][0]["coverage"] == 1
    assert plain["results"][0]["url"].startswith("https://")
    assert plain["results"][0]["local_path"].endswith("funcao-102--3742.md")
    assert all(result["module"] != "Fiscal" for result in plain["results"])
    assert [item["source_id"] for item in plain["results"]] == [
        item["source_id"] for item in prefixed["results"]
    ]


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell ausente")
def test_conversation_search_wrapper_runs_from_saved_workspace(tmp_path: Path) -> None:
    root = tmp_path / "VRProject"
    ensure_portable_project(root)
    article = root / "conhecimento" / "PDV" / "KB" / "pinpad.md"
    article.parent.mkdir(parents=True)
    article.write_text("Falha no pinpad durante a venda TEF.", encoding="utf-8")
    catalog = root / "indice" / "catalogo.jsonl"
    catalog.parent.mkdir(parents=True)
    catalog.write_text(
        json.dumps(
            {
                "source": "kb",
                "source_id": "wrapper-test",
                "title": "Falha no pinpad",
                "module": "PDV",
                "review_status": "approved",
                "status": "active",
                "local_path": "conhecimento/PDV/KB/pinpad.md",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    workspace = ensure_conversation_workspace(root / "TrabalhoVR" / "saved-thread")

    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(workspace / "tools" / "vr-search.ps1"),
            "-Query",
            "pinpad TEF",
        ],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
    )

    result = json.loads(completed.stdout)
    assert result["total"] == 1
    assert result["results"][0]["source_id"] == "wrapper-test"
