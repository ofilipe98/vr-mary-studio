"""Post-audit Tool Calling fixes (TC-01..TC-07) — surgical regressions.

Covers:
- TC-01 live == replay structural (reducer+registry single source)
- TC-02 snapshot replacement vs delta append + retry dedupe
- TC-03 UPDATED+exit_code no early terminal + terminal enrichment
- TC-04 provider streaming (Codex/Antigravity/OpenCode) same id/row growth
- TC-05 parallel anonymous tools never collide
- TC-06 approval requested->waiting, approved->running, denied->cancelled
- TC-07 menu target pin label (isConversationPinned)
"""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.frontend.chat import ChatBridge
from vrsoft_extractor.mary.models import RuntimeEvent
from vrsoft_extractor.mary.provider_adapters.tool_normalizer import (
    normalize_antigravity_event,
    normalize_codex_event,
    normalize_opencode_event,
)
from vrsoft_extractor.mary.tool_activity import (
    NormalizedToolEvent,
    ToolEventKind,
    ToolLifecycleReducer,
    ToolStatus,
    ToolType,
    coalesce_output,
)
from vrsoft_extractor.mary.tool_presentation import DEFAULT_PRESENTATION_REGISTRY


def _settings(root: Path) -> MarySettings:
    return MarySettings(app_dir=root, root=root / "VRProject", old_root=root / "legacy-source")


def _database(settings: MarySettings) -> MaryDatabase:
    return MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)


def _present(tool):
    pres = DEFAULT_PRESENTATION_REGISTRY.format(tool)
    d = pres.to_dict()
    d["id"] = tool.id
    if tool.output is not None:
        d["output"] = tool.output
    d["state"] = pres.state
    return d


COMPARED_KEYS = [
    "id", "state", "status", "text", "title", "subtitle",
    "badgeText", "badgeVariant", "icon", "errorSummary",
    "errorDetails", "command", "cwd", "exitCode", "output",
]


def _run_reducer(events, terminal):
    r = ToolLifecycleReducer()
    for ev in events:
        r.reduce(ev)
    if terminal is not None:
        r.finalize_turn(terminal)
    return {t.id: _present(t) for t in r.get_all_tools()}


class TestTC02SnapshotDelta(unittest.TestCase):
    def test_snapshot_progressive(self):
        out = coalesce_output(None, new_output="A", output_mode="snapshot")
        out = coalesce_output(out, new_output="AB", output_mode="snapshot")
        out = coalesce_output(out, new_output="ABC", output_mode="snapshot")
        self.assertEqual(out, "ABC")

    def test_snapshot_disjoint_replaces(self):
        self.assertEqual(
            coalesce_output("Downloading 10%", new_output="Downloading 20%", output_mode="snapshot"),
            "Downloading 20%",
        )
        self.assertEqual(
            coalesce_output("abc", new_output="xyz", output_mode="snapshot"),
            "xyz",
        )

    def test_delta_legit_repeats_append(self):
        r = ToolLifecycleReducer()
        r.reduce(NormalizedToolEvent(tool_id="c", kind=ToolEventKind.STARTED))
        r.reduce(NormalizedToolEvent(tool_id="c", kind=ToolEventKind.UPDATED, delta="A", output_mode="delta"))
        tool = r.reduce(NormalizedToolEvent(tool_id="c", kind=ToolEventKind.UPDATED, delta="A", output_mode="delta"))
        self.assertEqual(tool.output, "AA")

    def test_delta_same_event_id_dedupes(self):
        r = ToolLifecycleReducer()
        r.reduce(NormalizedToolEvent(tool_id="c", kind=ToolEventKind.STARTED))
        e = NormalizedToolEvent(tool_id="c", kind=ToolEventKind.UPDATED, delta="A", output_mode="delta", event_id="evt-1")
        r.reduce(e)
        tool = r.reduce(e)
        self.assertEqual(tool.output, "A")


class TestTC03ExitCodeTerminal(unittest.TestCase):
    def test_updated_exit_code_does_not_terminalize(self):
        r = ToolLifecycleReducer()
        r.reduce(NormalizedToolEvent(tool_id="t", kind=ToolEventKind.STARTED, type=ToolType.COMMAND_EXECUTION))
        t = r.reduce(NormalizedToolEvent(
            tool_id="t", kind=ToolEventKind.UPDATED, output="partial", exit_code=1,
        ))
        self.assertEqual(t.status, ToolStatus.RUNNING)
        self.assertEqual(t.exit_code, 1)
        self.assertEqual(t.output, "partial")

    def test_failed_enriches_after_updated_exit(self):
        r = ToolLifecycleReducer()
        r.reduce(NormalizedToolEvent(tool_id="t", kind=ToolEventKind.STARTED, type=ToolType.COMMAND_EXECUTION))
        r.reduce(NormalizedToolEvent(tool_id="t", kind=ToolEventKind.UPDATED, output="partial", exit_code=1))
        t = r.reduce(NormalizedToolEvent(
            tool_id="t", kind=ToolEventKind.FAILED,
            output="partial\nfull diagnostic", error="CompilationError",
        ))
        self.assertEqual(t.status, ToolStatus.FAILURE)
        self.assertIn("full diagnostic", str(t.output))
        self.assertEqual(t.error, "CompilationError")

    def test_terminal_state_cannot_regress_but_data_enriches(self):
        r = ToolLifecycleReducer()
        r.reduce(NormalizedToolEvent(tool_id="t", kind=ToolEventKind.STARTED))
        r.reduce(NormalizedToolEvent(tool_id="t", kind=ToolEventKind.COMPLETED, output="ok"))
        t = r.reduce(NormalizedToolEvent(
            tool_id="t", kind=ToolEventKind.FAILED, output="ok plus diag", error="Late",
        ))
        self.assertEqual(t.status, ToolStatus.SUCCESS)
        # Monotonic enrichment still applies without status regression.
        self.assertIn("plus diag", str(t.output))


class TestTC04ProviderStreaming(unittest.TestCase):
    def test_codex_output_delta_same_id_grows_no_dup(self):
        r = ToolLifecycleReducer()
        start = normalize_codex_event(
            {"item": {"id": "cx1", "type": "commandExecution", "command": ["npm", "test"]}},
            "item/started", "c",
        )
        self.assertIsNotNone(start)
        r.reduce(start)
        d1 = normalize_codex_event({"itemId": "cx1", "delta": "Downloading 10%"}, "item/commandExecution/outputDelta", "c")
        d2 = normalize_codex_event({"itemId": "cx1", "delta": " Downloading 20%"}, "item/outputDelta", "c")
        self.assertIsNotNone(d1)
        self.assertIsNotNone(d2)
        self.assertEqual(d1.tool_id, "cx1")
        self.assertEqual(d2.tool_id, "cx1")
        r.reduce(d1)
        tool = r.reduce(d2)
        self.assertEqual(tool.id, "cx1")
        self.assertIn("Downloading 10%", str(tool.output))
        self.assertIn("Downloading 20%", str(tool.output))
        self.assertEqual(len(r.get_all_tools()), 1)
        # item/updated with snapshot also routes to same row
        upd = normalize_codex_event(
            {"item": {"id": "cx1", "type": "commandExecution", "output": "Downloading 10% Downloading 20% done"}},
            "item/updated", "c",
        )
        self.assertIsNotNone(upd)
        tool2 = r.reduce(upd)
        self.assertEqual(tool2.id, "cx1")
        self.assertEqual(len(r.get_all_tools()), 1)

    def test_antigravity_tool_call_update_carries_output(self):
        start = normalize_antigravity_event(
            {"update": {"sessionUpdate": "tool_call", "toolCall": {"toolCallId": "ag1", "name": "bash", "arguments": {"CommandLine": "ls"}}}},
            "session/update", "c",
        )
        self.assertIsNotNone(start)
        r = ToolLifecycleReducer()
        r.reduce(start)
        upd = normalize_antigravity_event(
            {"update": {"sessionUpdate": "tool_call_update", "toolCall": {"toolCallId": "ag1", "name": "bash", "output": "file1\nfile2"}}},
            "session/update", "c",
        )
        self.assertIsNotNone(upd)
        self.assertEqual(upd.tool_id, "ag1")
        self.assertIsNotNone(upd.output)
        tool = r.reduce(upd)
        self.assertEqual(tool.id, "ag1")
        self.assertIn("file1", str(tool.output))
        self.assertEqual(len(r.get_all_tools()), 1)
        # Empty update (only id/name/input) must not create a bare event.
        empty = normalize_antigravity_event(
            {"update": {"sessionUpdate": "tool_call_update", "toolCall": {"toolCallId": "ag2", "name": "bash"}}},
            "session/update", "c",
        )
        self.assertIsNone(empty)

    def test_opencode_streaming_updates_same_id(self):
        r = ToolLifecycleReducer()
        s = normalize_opencode_event(
            {"type": "tool_use", "part": {"callID": "oc1", "tool": "bash", "state": "running", "args": {"command": "ls"}}},
            "c",
        )
        self.assertIsNotNone(s)
        r.reduce(s)
        u = normalize_opencode_event(
            {"type": "tool_use", "part": {"callID": "oc1", "tool": "bash", "state": "running", "output": "partial"}},
            "c",
        )
        self.assertIsNotNone(u)
        r.reduce(u)
        done = normalize_opencode_event(
            {"type": "tool_use", "part": {"callID": "oc1", "tool": "bash", "state": "completed", "output": "partial\nfull"}},
            "c",
        )
        tool = r.reduce(done)
        self.assertEqual(tool.id, "oc1")
        self.assertIn("full", str(tool.output))
        self.assertEqual(tool.status, ToolStatus.SUCCESS)
        self.assertEqual(len(r.get_all_tools()), 1)


def test_antigravity_typed_acp_updates_keep_one_tool_identity() -> None:
    reducer = ToolLifecycleReducer()
    start = normalize_antigravity_event(
        {
            "update": {
                "sessionUpdate": "tool_call",
                "toolCallId": "tool-typed-1",
                "title": "Run focused tests",
                "kind": "execute",
                "status": "in_progress",
                "rawInput": {"CommandLine": "pytest tests/test_one.py -q"},
            },
        },
        "session/update",
        "conversation",
    )
    assert start is not None
    reducer.reduce(start)

    for progress in range(1, 21):
        update = normalize_antigravity_event(
            {
                "update": {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "tool-typed-1",
                    "status": "inProgress",
                    "rawOutput": {"combinedOutput": f"progress {progress}/20"},
                },
            },
            "session/update",
            "conversation",
        )
        assert update is not None
        reducer.reduce(update)

    terminal = normalize_antigravity_event(
        {
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "tool-typed-1",
                "status": "completed",
                "rawOutput": {"combinedOutput": "20 passed", "exitCode": 0},
            },
        },
        "session/update",
        "conversation",
    )
    assert terminal is not None
    tool = reducer.reduce(terminal)

    assert len(reducer.get_all_tools()) == 1
    assert tool.id == "tool-typed-1"
    assert not tool.id.startswith("anon:")
    assert reducer.get_active_tools() == []
    assert tool.status == ToolStatus.SUCCESS
    assert tool.title == "Run focused tests"
    assert tool.command == "pytest tests/test_one.py -q"


class TestTC05AnonymousIdentity(unittest.TestCase):
    def test_two_anonymous_tools_do_not_collide(self):
        r = ToolLifecycleReducer()
        a = r.reduce(NormalizedToolEvent(tool_id="", kind=ToolEventKind.STARTED, execution_id=9, name="anon A"))
        b = r.reduce(NormalizedToolEvent(tool_id="tool", kind=ToolEventKind.STARTED, execution_id=9, name="anon B"))
        self.assertNotEqual(a.id, b.id)
        self.assertNotIn(a.id.lower(), {"tool", "unknown", "item", ""})
        self.assertNotIn(b.id.lower(), {"tool", "unknown", "item", ""})
        self.assertEqual(len(r.get_all_tools()), 2)
        ids = {t.id for t in r.get_all_tools()}
        self.assertEqual(len(ids), 2)


class TestTC01LiveReplayParity(unittest.TestCase):
    def _scenario_events(self, name):
        if name == "unfinished":
            return [
                NormalizedToolEvent(tool_id="t1", kind=ToolEventKind.STARTED, type=ToolType.COMMAND_EXECUTION, name="cmd", command="sleep 10", cwd="/tmp"),
            ], ToolStatus.INTERRUPTED
        if name == "completed":
            return [
                NormalizedToolEvent(tool_id="t1", kind=ToolEventKind.STARTED, type=ToolType.COMMAND_EXECUTION, name="cmd", command="echo hi", cwd="/tmp"),
                NormalizedToolEvent(tool_id="t1", kind=ToolEventKind.COMPLETED, output="hi", exit_code=0),
            ], None
        if name == "failed":
            return [
                NormalizedToolEvent(tool_id="t1", kind=ToolEventKind.STARTED, type=ToolType.COMMAND_EXECUTION, name="cmd", command="false", cwd="/tmp"),
                NormalizedToolEvent(tool_id="t1", kind=ToolEventKind.FAILED, output="err", error="CompilationError", exit_code=1),
            ], None
        if name == "cancelled":
            return [
                NormalizedToolEvent(tool_id="t1", kind=ToolEventKind.STARTED, type=ToolType.COMMAND_EXECUTION, name="cmd", command="sleep 10"),
                NormalizedToolEvent(tool_id="t1", kind=ToolEventKind.CANCELLED),
            ], None
        raise AssertionError(name)

    def test_live_equals_replay_structural(self):
        for scenario in ["unfinished", "completed", "failed", "cancelled"]:
            events, terminal = self._scenario_events(scenario)
            live = _run_reducer(list(events), terminal)
            # Replay: fresh reducer, same persisted order, same terminal detection.
            replay = _run_reducer(list(events), terminal)
            self.assertIn("t1", live)
            self.assertIn("t1", replay)
            for key in COMPARED_KEYS:
                self.assertEqual(live["t1"][key], replay["t1"][key], f"{scenario}:{key}")

    def test_unfinished_becomes_interrupted_completed_failed_cancelled_stay(self):
        live_u = _run_reducer(*self._scenario_events("unfinished"))
        self.assertEqual(live_u["t1"]["state"], "interrupted")
        live_c = _run_reducer(*self._scenario_events("completed"))
        self.assertEqual(live_c["t1"]["state"], "completed")
        live_f = _run_reducer(*self._scenario_events("failed"))
        self.assertEqual(live_f["t1"]["state"], "error")
        live_x = _run_reducer(*self._scenario_events("cancelled"))
        self.assertEqual(live_x["t1"]["state"], "cancelled")


class TestTC06ApprovalLifecycle(unittest.TestCase):
    def test_requested_granted_denied(self):
        r = ToolLifecycleReducer()
        waiting = r.reduce(NormalizedToolEvent(
            tool_id="ap1", kind=ToolEventKind.APPROVAL_REQUESTED,
            type=ToolType.COMMAND_EXECUTION, command="rm -rf /tmp/x",
        ))
        self.assertEqual(waiting.status, ToolStatus.WAITING_APPROVAL)
        pres = DEFAULT_PRESENTATION_REGISTRY.format(waiting)
        self.assertEqual(pres.state, "waiting_approval")

        r2 = ToolLifecycleReducer()
        r2.reduce(NormalizedToolEvent(tool_id="ap2", kind=ToolEventKind.APPROVAL_REQUESTED, type=ToolType.COMMAND_EXECUTION))
        granted = r2.reduce(NormalizedToolEvent(tool_id="ap2", kind=ToolEventKind.APPROVAL_RESOLVED, approved=True))
        self.assertEqual(granted.status, ToolStatus.RUNNING)

        r3 = ToolLifecycleReducer()
        r3.reduce(NormalizedToolEvent(tool_id="ap3", kind=ToolEventKind.APPROVAL_REQUESTED, type=ToolType.COMMAND_EXECUTION))
        denied = r3.reduce(NormalizedToolEvent(tool_id="ap3", kind=ToolEventKind.APPROVAL_RESOLVED, approved=False))
        self.assertEqual(denied.status, ToolStatus.CANCELLED)
        pres_d = DEFAULT_PRESENTATION_REGISTRY.format(denied)
        self.assertEqual(pres_d.badge_text, "negado")


class TestTC07MenuTarget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self._settings = _settings(root)
        self._database = _database(self._settings)
        self._prefs = QSettings(str(root / "prefs.ini"), QSettings.IniFormat)
        self._bridge = ChatBridge(self._settings, self._database, self._prefs)
        self.addCleanup(self._bridge.close)

    def test_target_pin_label_not_selection(self):
        c1 = self._database.create_conversation("C1", "codex", "m", self._settings.root)
        c2 = self._database.create_conversation("C2", "codex", "m", self._settings.root)
        self._bridge.refresh()
        self._bridge.selectConversationId(c1)
        # Pin selected, target unpinned -> target label must be Fixar.
        self._bridge.togglePinnedConversation(c1)
        self.assertTrue(self._bridge.isConversationPinned(c1))
        self.assertFalse(self._bridge.isConversationPinned(c2))
        # Act on target: pin target, selection unchanged.
        self._bridge.togglePinnedConversation(c2)
        self.assertTrue(self._bridge.isConversationPinned(c2))
        self.assertEqual(self._bridge._selected_conversation_id(), c1)
        # Inverse: unpin target while selected stays pinned.
        self._bridge.togglePinnedConversation(c2)
        self.assertFalse(self._bridge.isConversationPinned(c2))
        self.assertTrue(self._bridge.isConversationPinned(c1))
        # QML uses target state, not selectedPinned.
        qml = (Path(__file__).resolve().parent.parent
               / "vrsoft_extractor" / "mary" / "frontend" / "qml" / "pages" / "ChatPreview.qml").read_text(encoding="utf-8")
        self.assertIn("isConversationPinned", qml)
        self.assertIn("conversationMenuConversationId", qml)
        # The pin row must no longer depend solely on selectedPinned.
        pin_lines = [ln for ln in qml.splitlines() if "Fixar conversa" in ln]
        self.assertTrue(pin_lines)
        self.assertTrue(any("isConversationPinned" in ln for ln in pin_lines))


class TestTC01BridgeReloadParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self._settings = _settings(root)
        self._database = _database(self._settings)
        self._prefs = QSettings(str(root / "prefs.ini"), QSettings.IniFormat)
        self._bridge = ChatBridge(self._settings, self._database, self._prefs)
        self.addCleanup(self._bridge.close)

    def _reload_cards(self, tool_payloads, terminal="turn_completed"):
        cid = self._database.create_conversation("R", "codex", "m", self._settings.root)
        eid = 21
        for p in tool_payloads:
            payload = dict(p)
            payload.setdefault("execution_id", eid)
            self._database.add_event(RuntimeEvent(cid, "tool_event", "", payload))
        self._database.add_event(RuntimeEvent(cid, terminal, "", {"execution_id": eid}))
        self._database.begin_user_turn(cid, "hi")
        rows = self._database.messages(cid)
        prefs2 = QSettings(str(Path(self._tmp.name) / f"{cid}.ini"), QSettings.IniFormat)
        bridge2 = ChatBridge(self._settings, self._database, prefs2)
        self.addCleanup(bridge2.close)
        bridge2._selected = {"conversationId": cid}
        self.assertTrue(bridge2._reload_execution_timeline(cid, rows))
        cards = {}
        for m in bridge2._messages._items:
            for t in m.get("activityData", []):
                cards[t["id"]] = t
        return cards

    def test_reload_terminal_mapping(self):
        c_u = self._reload_cards([{"toolCallId": "u1", "step_type": "commandExecution", "status": "running"}])
        self.assertEqual(c_u["u1"]["state"], "interrupted")
        c_ok = self._reload_cards([
            {"toolCallId": "o1", "step_type": "commandExecution", "status": "running"},
            {"toolCallId": "o1", "step_type": "commandExecution", "status": "success", "output": "ok"},
        ])
        self.assertEqual(c_ok["o1"]["state"], "completed")
        c_err = self._reload_cards([
            {"toolCallId": "e1", "step_type": "commandExecution", "status": "running"},
            {"toolCallId": "e1", "step_type": "commandExecution", "status": "error", "error": "boom"},
        ])
        self.assertEqual(c_err["e1"]["state"], "error")
        c_cancel = self._reload_cards(
            [{"toolCallId": "x1", "step_type": "commandExecution", "status": "running"}],
            terminal="orchestration_cancelled",
        )
        self.assertEqual(c_cancel["x1"]["state"], "cancelled")


if __name__ == "__main__":
    unittest.main()
