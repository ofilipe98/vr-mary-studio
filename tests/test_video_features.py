import shutil
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vrsoft_extractor.courses import (
    _enroll_one,
    _iter_course_summaries,
    _request_json,
    course_from_payload,
    parse_course_selections,
)
from vrsoft_extractor.downloader import (
    _download_candidates,
    _download_target_bases,
    _find_existing_download,
    organize_downloads,
)
from vrsoft_extractor.inventory import load_inventory, merge_inventory, save_inventory
from vrsoft_extractor.models import VideoItem
from vrsoft_extractor.scanner import SectionSpec, scan
from vrsoft_extractor.settings import ConfigError, Settings
from vrsoft_extractor.utils import output_base_path
from vrsoft_extractor.video_classification import (
    classify_inventory,
    load_module_overrides,
    save_module_override,
    save_module_overrides,
)
from vrsoft_extractor.video_storage import format_byte_size, inspect_video_storage


def video(
    *,
    area="curso",
    course="Integração Squad Fiscal",
    chapter="Apresentação",
    title="Introdução",
    page="https://example.com/course/1/task/1",
    media="https://cdn.example.com/shared.mp4?token=one",
    course_id="1",
    task_id="1",
):
    return VideoItem(
        area=area,
        course=course,
        module=chapter,
        folder_path=[course, chapter] if area == "curso" else [course, chapter],
        source_course_id=course_id if area == "curso" else "",
        source_task_id=task_id if area == "curso" else "",
        source_file_id=task_id if area == "biblioteca" else "",
        lesson_title=title,
        page_url=page,
        media_url=media,
        media_type="mp4",
    )


def test_shared_media_is_not_deduplicated_across_lessons():
    first = video(task_id="1", page="https://example.com/task/1")
    second = video(task_id="2", page="https://example.com/task/2")
    merged = merge_inventory([], [first, second])
    assert len(merged) == 2


def test_expiring_query_does_not_duplicate_same_task():
    first = video(media="https://cdn.example.com/aula.mp4?token=old")
    second = video(media="https://cdn.example.com/aula.mp4?token=new")
    merged = merge_inventory([first], [second])
    assert len(merged) == 1
    assert merged[0].media_url.endswith("token=new")


def test_legacy_item_is_upgraded_without_duplication():
    legacy = video(course_id="", task_id="")
    discovered = video(course_id="99", task_id="101")
    legacy.status = "downloaded"
    legacy.local_path = "downloads/old.mp4"
    merged = merge_inventory([legacy], [discovered])
    assert len(merged) == 1
    assert merged[0].source_course_id == "99"
    assert merged[0].status == "downloaded"
    assert merged[0].local_path == "downloads/old.mp4"


def test_legacy_inventory_builds_folder_path():
    item = VideoItem.from_dict(
        {
            "area": "biblioteca",
            "course": "VR Master",
            "module": "Financeiro / Contas a pagar",
            "lesson_title": "Introdução.mp4",
            "page_url": "https://example.com/file/1",
            "media_url": "https://cdn.example.com/1.mp4",
            "media_type": "mp4",
        }
    )
    assert item.folder_path == ["VR Master", "Financeiro", "Contas a pagar"]


def test_classification_inherits_course_module():
    rows = classify_inventory([video()])
    assert rows[0].business_module == "Fiscal"
    assert rows[0].classification_status == "approved"
    assert rows[0].classification_source == "course_inherited"


@pytest.mark.parametrize(
    ("folder_path", "expected"),
    [
        (["VR Master", "Financeiro", "TEF", "Transação"], "ADM_FIN_ESTOQUE"),
        (["VR Master", "Nota Fiscal", "Recebimento"], "Fiscal"),
        (
            ["VR Master", "Contabilidade", "Arquivos Magnéticos", "DIME"],
            "Fiscal",
        ),
        (["VR Master", "Estoque", "Produção", "Consumo"], "ADM_FIN_ESTOQUE"),
        (["VR Master", "Sistema", "Serviços Web Sefaz"], "ADM_FIN_ESTOQUE"),
        (["VR Master", "PDV", "TEF", "Transação"], "PDV"),
    ],
)
def test_classification_uses_explicit_vrmaster_menu_hierarchy(
    folder_path, expected
):
    item = video(
        area="biblioteca",
        course=folder_path[0],
        chapter=folder_path[-2],
        title=folder_path[-1],
    )
    item.folder_path = folder_path

    rows = classify_inventory([item])

    assert rows[0].business_module == expected
    assert rows[0].classification_status == "approved"
    assert rows[0].classification_source == "course_inherited"


def _test_dir() -> Path:
    path = Path(".test-tmp") / f"video-features-{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_manual_group_override_has_precedence():
    tmp_path = _test_dir()
    item = video(course="Database Lab", chapter="Database Lab")
    try:
        override_path = tmp_path / "overrides.json"
        save_module_override(
            override_path,
            key=item.group_key(),
            module="ADM_FIN_ESTOQUE",
            scope="groups",
        )
        classify_inventory([item], override_path)
        assert item.business_module == "ADM_FIN_ESTOQUE"
        assert item.classification_source == "manual_group"
        assert item.classification_confidence == 1.0
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_manual_overrides_are_atomic_and_corruption_is_not_silently_ignored():
    tmp_path = _test_dir()
    try:
        override_path = tmp_path / "overrides.json"
        save_module_overrides(
            override_path,
            [
                ("groups", "course:1", "Fiscal"),
                ("items", "task:2", "PDV"),
            ],
        )
        loaded = load_module_overrides(override_path)
        assert loaded["groups"]["course:1"] == "Fiscal"
        assert loaded["items"]["task:2"] == "PDV"

        override_path.write_text("{inválido", encoding="utf-8")
        try:
            load_module_overrides(override_path)
        except ValueError as exc:
            assert "inválido" in str(exc)
        else:
            raise AssertionError("Configuração corrompida foi tratada como vazia")
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_scan_failure_preserves_previous_inventory():
    tmp_path = _test_dir().resolve()
    settings = Settings(project_dir=tmp_path)
    existing = video(title="Inventário anterior")
    save_inventory(
        [existing], settings.inventory_json_path, settings.inventory_csv_path
    )
    before = settings.inventory_json_path.read_bytes()
    playwright_context = MagicMock()
    runtime = MagicMock()
    browser = MagicMock()
    runtime.chromium.launch.return_value = browser
    browser.new_context.return_value.new_page.return_value = MagicMock()
    playwright_context.__enter__.return_value = runtime
    try:
        with (
            patch("playwright.sync_api.sync_playwright", return_value=playwright_context),
            patch("vrsoft_extractor.scanner.ensure_session"),
            patch("vrsoft_extractor.scanner.configure_playwright_runtime"),
            patch(
                "vrsoft_extractor.scanner.SECTION_SPECS",
                (SectionSpec("curso", "Cursos", "/cursos"),),
            ),
            patch(
                "vrsoft_extractor.scanner._crawl_api_section",
                side_effect=RuntimeError("API indisponível"),
            ),
        ):
            try:
                scan(settings)
            except RuntimeError as exc:
                assert "inventário anterior foi preservado" in str(exc)
            else:
                raise AssertionError("Falha parcial da varredura foi tratada como sucesso")

        assert settings.inventory_json_path.read_bytes() == before
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_classified_output_path_preserves_hierarchy_and_extension():
    path = output_base_path(
        Path("downloads"),
        "curso",
        "Curso",
        "Capítulo",
        "Introdução.mp4",
        business_module="Fiscal",
        folder_path=["Curso", "Capítulo"],
    )
    assert path == Path("downloads/Cursos/Fiscal/Curso/Capítulo/Introdução")


def test_duplicate_lesson_titles_receive_deterministic_suffix():
    settings = Settings(project_dir=Path("D:/project"))
    first = video(task_id="10", title="Introdução")
    second = video(task_id="11", title="Introdução", page="https://example.com/task/11")
    first.business_module = second.business_module = "Fiscal"
    targets = _download_target_bases([second, first], settings)
    assert targets[first.id].name == "Introdução"
    assert targets[second.id].name == "Introdução - 11"


def test_existing_download_ignores_thumbnail_and_empty_video():
    tmp_path = _test_dir()
    try:
        base = tmp_path / "aula"
        base.with_suffix(".jpg").write_bytes(b"thumbnail")
        base.with_suffix(".mp4").touch()
        assert _find_existing_download(base) is None

        base.with_suffix(".mp4").write_bytes(b"video")
        assert _find_existing_download(base) == base.with_suffix(".mp4")
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_download_candidates_recover_missing_file_and_honor_redownload():
    tmp_path = _test_dir().resolve()
    settings = Settings(project_dir=tmp_path)
    missing = video(task_id="missing")
    missing.status = "downloaded"
    missing.local_path = str(tmp_path / "downloads" / "missing.mp4")
    valid = video(task_id="valid", page="https://example.com/task/valid")
    valid.status = "downloaded"
    valid_path = tmp_path / "downloads" / "valid.mp4"
    valid_path.parent.mkdir(parents=True)
    valid_path.write_bytes(b"video")
    valid.local_path = str(valid_path)
    protected = video(task_id="protected", page="https://example.com/task/protected")
    protected.status = "protected"
    try:
        regular = _download_candidates(
            [missing, valid, protected], settings, redownload=False
        )
        forced = _download_candidates(
            [missing, valid, protected], settings, redownload=True
        )

        assert regular == [missing]
        assert forced == [missing, valid, protected]
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_download_candidates_honor_individual_video_selection():
    first = video(task_id="selected", title="Selecionado")
    second = video(task_id="other", title="Outro")
    settings = Settings(project_dir=_test_dir())

    selected = _download_candidates(
        [first, second],
        settings,
        redownload=False,
        item_ids={first.id},
    )

    assert [item.id for item in selected] == [first.id]


def test_video_storage_detects_downloads_and_missing_files():
    tmp_path = _test_dir().resolve()
    settings = Settings(project_dir=tmp_path)
    downloaded = video(task_id="20", title="Aula baixada")
    downloaded.business_module = "Fiscal"
    missing = video(
        task_id="21",
        title="Aula ausente",
        page="https://example.com/task/21",
    )
    missing.business_module = "Fiscal"
    missing.status = "downloaded"
    missing.local_path = str(tmp_path / "downloads" / "arquivo-inexistente.mp4")
    try:
        target = _download_target_bases([downloaded, missing], settings)[downloaded.id]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.with_suffix(".mp4").write_bytes(b"x" * 2048)

        storage = inspect_video_storage([downloaded, missing], settings)

        assert storage[downloaded.id].state == "Baixado"
        assert storage[downloaded.id].size_bytes == 2048
        assert format_byte_size(storage[downloaded.id].size_bytes) == "2,0 KB"
        assert storage[missing.id].state == "Arquivo ausente"
        assert not storage[missing.id].downloaded
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_course_catalog_statuses():
    enrolled = course_from_payload(
        {"id": 1, "name": "Treinamento PDV Pro", "participant": {"id": 9}},
        {"id": 1, "name": "Treinamento PDV Pro", "participant": {"id": 9}},
    )
    assert enrolled.status == "enrolled"
    assert enrolled.business_module == "PDV"

    available = course_from_payload(
        {"id": 2, "name": "VR Master - Financeiro"},
        {
            "id": 2,
            "name": "VR Master - Financeiro",
            "application_method": "1",
            "available_classes": [{"id": 22, "closed": 0, "date_start": "2026-08-01"}],
        },
    )
    assert available.status == "available"
    assert available.selected_class_id == "22"
    assert available.selectable

    waitlist = course_from_payload(
        {"id": 3, "name": "Curso"},
        {
            "id": 3,
            "name": "Curso",
            "application_method": "3",
            "available_classes": [{"id": 33, "closed": 0}],
        },
    )
    assert waitlist.status == "waitlist"
    assert not waitlist.selectable

    unavailable = course_from_payload(
        {"id": 4, "name": "Curso"},
        {"id": 4, "name": "Curso", "application_method": "1", "available_classes": []},
    )
    assert unavailable.status == "unavailable"


def test_parse_course_selection_requires_course_and_class():
    assert parse_course_selections(["10:20", "30:40"]) == [("10", "20"), ("30", "40")]
    try:
        parse_course_selections(["10"])
    except ConfigError:
        pass
    else:
        raise AssertionError("Invalid selection was accepted")


def test_course_inventory_does_not_treat_malformed_response_as_empty():
    with pytest.raises(ConfigError, match="inventário inválido"):
        list(_iter_course_summaries(lambda _url: {}, 2))


def test_course_request_distinguishes_http_and_json_errors():
    page = MagicMock()
    page.request.get.return_value = _Response([], status=503)
    with pytest.raises(ConfigError, match="HTTP 503"):
        _request_json(page, {}, "https://example.com/courses")

    response = MagicMock(status=200)
    response.json.side_effect = ValueError("broken")
    page.request.get.return_value = response
    with pytest.raises(ConfigError, match="JSON inválido"):
        _request_json(page, {}, "https://example.com/courses")


class _Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def json(self):
        return self.payload


class _Request:
    def __init__(self, details, post_payload=None):
        self.details = list(details)
        self.post_payload = post_payload or {"redirect": "/cursos"}
        self.posts = []

    def get(self, _url, headers=None):
        del headers
        return _Response(self.details.pop(0))

    def post(self, url, headers=None, data=None):
        del headers
        self.posts.append((url, data))
        return _Response(self.post_payload)


class _Page:
    def __init__(self, request):
        self.request = request

    def wait_for_timeout(self, _milliseconds):
        return None


def test_enroll_one_posts_selected_course_and_verifies_participant():
    available = {
        "id": 10,
        "name": "VR Master - Financeiro",
        "application_method": "1",
        "available_classes": [{"id": 20, "closed": 0}],
        "participant": None,
    }
    verified = {**available, "participant": {"id": 30, "course_class_id": 20}}
    request = _Request([available, verified])
    result = _enroll_one(_Page(request), {}, "10", "20")
    assert result["success"]
    assert request.posts[0][1] == {"id": 10, "class_id": 20}


def test_enroll_one_does_not_post_waitlist_course():
    waitlist = {
        "id": 10,
        "name": "Curso",
        "application_method": "3",
        "available_classes": [{"id": 20, "closed": 0}],
        "participant": None,
    }
    request = _Request([waitlist])
    result = _enroll_one(_Page(request), {}, "10", "20")
    assert not result["success"]
    assert request.posts == []


def test_video_output_decoder_preserves_split_utf8_character():
    from vrsoft_extractor.mary.ui import (
        new_video_output_decoder,
        video_process_command,
        video_process_environment,
    )

    decoder = new_video_output_decoder()
    encoded = "Treinamento Força de Vendas".encode("utf-8")
    split = encoded.index("ç".encode("utf-8")) + 1
    text = decoder.decode(encoded[:split], final=False)
    text += decoder.decode(encoded[split:], final=True)
    assert text == "Treinamento Força de Vendas"
    environment = video_process_environment()
    assert environment.value("PYTHONUTF8") == "1"
    assert environment.value("PYTHONIOENCODING") == "utf-8"
    executable, development = video_process_command(
        Path("VRProject"), "scan", frozen=False
    )
    assert executable
    assert development[:2] == ["-m", "vrsoft_extractor"]
    _executable, packaged = video_process_command(
        Path("VRProject"), "scan", frozen=True
    )
    assert packaged[:2] == ["--video-cli", "--project-dir"]


def test_studio_main_routes_packaged_video_cli_without_opening_gui():
    from vrsoft_extractor.mary import ui

    with patch("vrsoft_extractor.cli.main", return_value=7) as video_main:
        result = ui.main(["--video-cli", "--project-dir", "VRProject", "scan"])

    assert result == 7
    video_main.assert_called_once_with(
        ["--project-dir", "VRProject", "scan"]
    )


def test_organize_downloads_moves_without_overwriting():
    tmp_path = _test_dir()
    settings = Settings(project_dir=tmp_path.resolve())
    tmp_path = settings.project_dir
    try:
        source = tmp_path / "downloads" / "old" / "aula.mp4"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"video")
        item = video(title="Aula")
        item.business_module = "Fiscal"
        item.status = "downloaded"
        item.local_path = str(source)
        settings.metadata_dir.mkdir(parents=True)
        save_inventory([item], settings.inventory_json_path, settings.inventory_csv_path)

        result = organize_downloads(settings)
        expected = tmp_path / "downloads" / "Cursos" / "Fiscal" / item.course / item.module / "Aula.mp4"
        assert result["moved"] == 1
        assert expected.exists()
        assert not source.exists()
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_organize_downloads_rolls_back_move_when_inventory_save_fails():
    tmp_path = _test_dir()
    settings = Settings(project_dir=tmp_path.resolve())
    try:
        source = settings.downloads_dir / "old" / "aula.mp4"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"video")
        item = video(title="Aula")
        item.business_module = "Fiscal"
        item.status = "downloaded"
        item.local_path = str(source)
        save_inventory(
            [item], settings.inventory_json_path, settings.inventory_csv_path
        )

        with patch(
            "vrsoft_extractor.downloader.save_inventory",
            side_effect=OSError("disco indisponível"),
        ):
            try:
                organize_downloads(settings)
            except OSError:
                pass
            else:
                raise AssertionError("A falha de persistência foi ocultada")

        assert source.is_file()
        persisted = load_inventory(settings.inventory_json_path)
        assert persisted[0].local_path == str(source)
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)
