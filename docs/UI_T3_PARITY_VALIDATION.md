# UI T3 Parity Validation

Base SHA: `766fa0eae53d263ef452dd7fbf3c46ecefdbe18d` (dev == main, already synced; `git fetch` shows no divergence).
T3 Code ref: `https://github.com/pingdotgg/t3code`, branch `main`, fetched 2026-09-18.
T3 files consulted: `apps/web/src/components/ui/button.tsx`, `apps/web/src/components/ui/input.tsx`, `apps/web/src/components/ui/select.tsx`.
T3 desktop values confirmed: button default `h-9`/`sm:h-8` (36/32px), input `h-8.5`/`sm:h-7.5` (34/30px), select default `min-h-9`/`sm:min-h-8` (36/32px), controls `text-base`/`sm:text-sm` (16/14px).

## Resolutions matrix

| Item | Change |
|---|---|
| Font migration | `bridge.py` preserves `interface_font_family` on v2->v3 size 14->16; new `tests/test_interface_typography_migration.py` (8 tests) |
| Controls typography | `VrTextField`/`VrTextArea`/`VrComboBox`/`VrCheckBox` use `Theme.controlSize` (14); `VrButton` already 14; `VrNavItem` already 14 |
| Density | `VrTextField`/`VrComboBox`/`VrButton` default to `controlHeightCompact` (32); `VrIconButton` to `iconButtonNormal` (34); new `menuRowHeight` (32)/`pickerRowHeight` (40) tokens; combo delegate uses tokens |
| Review narrow | `ReviewPage` vertical `SplitView` when `width<900`, secondary columns hidden (detail markdown already carries fonte/produto/categoria/confianca), adaptive filter grid (2/3/6 cols), responsive bulk dialog |
| Applications | 18x `Theme.fontSize(11)` -> `Theme.fontSizeMicro` (same 11px, semantic token) |
| TitleBar | brand 13->14 (`controlSize`), breadcrumb project/title 12->14, separator 12->caption (12); all `NativeRendering` -> `Theme.textRenderType`; badge stays micro |
| Rendering | removed all hardcoded `Text.NativeRendering` (composer, model/reasoning/permission pickers, titlebar); `Theme.textRenderType` policy documented; `QQuickWindow` global now follows `fontSmoothing` via `bridge.setFontSmoothing` + `create_engine` |
| Line-height | `bodyLineHeight` on AppearanceRow description, EmptyState description, Review bulk dialog, approval reason (+ existing chat agent label); `denseLineHeight` on context excerpt; `headingLineHeight` on PageHeader/EmptyState titles; Markdown rhythm via `styleMessageDocument` (TextEdit has no QML `lineHeight`) |
| Dialogs narrow | `conversationDeleteDialog`/`chatApprovalDialog`/`bulkDecisionDialog` width `min(fixed, parent.width-32)` |
| Visual script | new `scripts/visual_core_pages_review.py`: core pages (0/2/3/4/5/6), real browser/terminal surfaces, 11 dialogs/pickers |

## Matrices

Resolutions: 390x844, 768x1024, 1366x768, 1920x1080. Scales: 100% all; 125% narrow+desktop (390, 1366); 150% desktop (1366, 1920). Themes: `dark_orange`, `light`.

## Tests

- `pytest -q -m "not qml"`: 960 passed (incl. 8 new migration tests).
- `pytest -q -m qml`: 169 passed.
- Total: 1129 passed, 0 failed, 0 skipped (45 subtests passed).
- `ruff check .`: 12 pre-existing F401 in `tests/test_application_import_flow.py` and `tests/test_code_inspection_and_synthesis_fix.py` (untouched, out of scope).

## Visual reviews (QML warnings = 0 each)

- `visual_chat_review.py` (.test-tmp/visual-review): 36 captures, 0 warnings.
- `visual_settings_all_tabs_review.py` (.test-tmp/settings-review): 264 captures, 0 warnings.
- `visual_appearance_review.py` (.test-tmp/appearance-review): 94 captures, 0 warnings.
- `visual_core_pages_review.py` (.test-tmp/core-pages-review): 176 captures, 0 QML warnings, 42 geometry notes (below).

## Clipping/overlap

No regressions introduced (shared control height 38->32 only reduces vertical size; no width minima added).
Pre-existing narrow-shell notes (hub navigation 220px fixed + desktop-first page minima overflow viewport at 390/768 for all hub pages incl. Review inner SplitView allocation; surface collapse button at 390; composer toolbar scrolls in Flickable): recorded in `core-pages-review/results.json` issues (42). ReviewPage inner layout itself is adaptive (no 950px minima, no sub-micro fonts); end-to-end narrow needs follow-up hub-shell navigation redesign.

## Remaining limitations

- Hub shell navigation overflows at 390/768 (all hub pages); documented, not introduced here.
- `ruff` pre-existing F401 noted above.
- No screenshots committed (captures under `.test-tmp/`, git-ignored).
