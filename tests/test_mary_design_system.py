import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QAbstractAnimation, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QLineEdit, QWidget

from vrsoft_extractor.mary.chat_widgets import (
    AnimatedVrFlowButton,
    VrComposerGlowFrame,
)
from vrsoft_extractor.mary.design_system import (
    ActionButton,
    ConfirmDialog,
    ContextActionMenu,
    DataContentStack,
    DataToolbar,
    FormField,
    PaginationBar,
    ProjectScopeButton,
    ProjectScopePopup,
    SimpleFilterGroup,
    StatusBadge,
    SurfaceMenu,
    TextPromptDialog,
    ToastBanner,
    VrModePopup,
)


class MaryDesignSystemTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_project_scope_button_is_keyboard_and_mouse_accessible(self):
        button = ProjectScopeButton()
        button.setText("cliente-a")
        activations = []
        button.clicked.connect(lambda: activations.append(True))

        button.show()
        QTest.keyClick(button, Qt.Key_Return)
        QTest.mouseClick(button, Qt.LeftButton)

        self.assertEqual(button.text(), "cliente-a")
        self.assertEqual(len(activations), 2)
        self.assertEqual(button.focusPolicy(), Qt.StrongFocus)
        button.close()

    def test_project_scope_popup_exposes_only_scope_and_recent_projects(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            projects = []
            for name in ("alpha", "beta"):
                project = root / name
                project.mkdir()
                projects.append(project.resolve())
            button = ProjectScopeButton()
            popup = ProjectScopePopup(button)
            popup.set_projects(projects, projects[1])

            self.assertEqual(
                [action.text() for action in popup.actions()],
                [
                    "Todos os projetos",
                    "alpha",
                    "beta",
                ],
            )
            self.assertFalse(hasattr(popup, "add_button"))
            self.assertLess(
                popup.layout().indexOf(popup.search),
                popup.layout().indexOf(popup.scroll),
            )
            self.assertEqual(len(popup._rows), 3)
            self.assertTrue(popup._rows[2].property("selected"))
            popup.close()
            button.close()

    def test_project_scope_popup_filters_and_emits_selection(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            projects = []
            for index in range(6):
                project = root / f"cliente-{index}"
                project.mkdir()
                projects.append(project.resolve())
            button = ProjectScopeButton()
            popup = ProjectScopePopup(button)
            selected = []
            popup.projectSelected.connect(selected.append)
            popup.set_projects(projects, None)

            self.assertFalse(popup.search.isHidden())
            popup.search.setText("cliente-4")
            self.application.processEvents()
            self.assertEqual(len(popup._rows), 1)
            popup._activate_project(projects[4])
            self.assertEqual(selected, [projects[4]])
            popup.close()
            button.close()

    def test_project_rows_offer_canonical_open_and_remove_actions(self):
        with TemporaryDirectory() as temporary:
            project = Path(temporary).resolve()
            button = ProjectScopeButton()
            popup = ProjectScopePopup(button)
            opened = []
            removed = []
            popup.openProjectRequested.connect(opened.append)
            popup.removeProjectRequested.connect(removed.append)
            popup.set_projects([project], project)

            row = popup._rows[1]
            self.assertIsInstance(row.action_menu, ContextActionMenu)
            self.assertEqual(
                [action.text() for action in row.action_menu.actions()],
                ["Abrir pasta", "Remover da lista"],
            )
            row.openRequested.emit(project)
            row.removeRequested.emit(project)
            self.assertEqual(opened, [project])
            self.assertEqual(removed, [project])
            popup.close()
            button.close()

    def test_simple_filter_group_counts_and_resets_search_and_selectors(self):
        search = QLineEdit()
        source = QComboBox()
        source.addItems(["Todas", "Wiki"])
        module = QComboBox()
        module.addItems(["Todos", "Fiscal"])
        filters = SimpleFilterGroup(
            search=search,
            selectors=(source, module),
        )
        counts = []
        filters.activeCountChanged.connect(counts.append)

        search.setText("pix")
        source.setCurrentIndex(1)
        module.setCurrentIndex(1)
        self.assertEqual(filters.active_count(), 3)
        filters.reset()

        self.assertEqual(filters.active_count(), 0)
        self.assertEqual(search.text(), "")
        self.assertEqual(source.currentIndex(), 0)
        self.assertEqual(module.currentIndex(), 0)
        self.assertEqual(counts[-1], 0)

    def test_surface_menu_has_shared_identity_and_stable_width(self):
        menu = SurfaceMenu()
        self.assertEqual(menu.objectName(), "surfaceMenu")
        self.assertGreaterEqual(menu.minimumWidth(), 196)
        menu.close()

    def test_canonical_action_form_and_status_components_expose_semantics(self):
        action = ActionButton("Excluir", variant="danger")
        field_control = QLineEdit()
        field = FormField(
            "Projeto",
            field_control,
            help_text="Escolha uma pasta local.",
        )
        badge = StatusBadge("Executando", kind="running")
        try:
            self.assertEqual(action.variant(), "danger")
            action.set_variant("unknown")
            self.assertEqual(action.variant(), "secondary")
            self.assertEqual(field_control.accessibleName(), "Projeto")
            field.set_error("A pasta não existe.")
            self.assertTrue(field.error_label.isVisibleTo(field))
            self.assertEqual(field_control.property("validationState"), "error")
            field.set_error("")
            self.assertTrue(field.error_label.isHidden())
            self.assertEqual(badge.property("statusKind"), "running")
            self.assertEqual(badge.accessibleName(), "Status: Executando")
        finally:
            badge.close()
            field.close()
            action.close()

    def test_destructive_confirmation_requires_typed_phrase(self):
        dialog = ConfirmDialog(
            "Excluir conversa definitivamente?",
            "Esta ação não pode ser desfeita.",
            destructive=True,
            confirmation_phrase="EXCLUIR",
        )
        self.assertIsNotNone(dialog.phrase_input)
        self.assertFalse(dialog.confirm_button.isEnabled())

        dialog.phrase_input.setText("excluir")
        self.assertTrue(dialog.confirm_button.isEnabled())
        QTest.keyClick(dialog.phrase_input, Qt.Key_Return)
        self.assertEqual(dialog.result(), QDialog.Accepted)
        dialog.close()

    def test_text_prompt_blocks_empty_and_unchanged_branches(self):
        dialog = TextPromptDialog(
            "Editar mensagem",
            "A correção será enviada em uma nova ramificação:",
            "Mensagem original",
        )
        self.assertFalse(dialog.confirm_button.isEnabled())
        dialog.editor.setPlainText("   ")
        self.assertFalse(dialog.confirm_button.isEnabled())
        dialog.editor.setPlainText("Mensagem corrigida")
        self.assertTrue(dialog.confirm_button.isEnabled())
        self.assertEqual(dialog.value(), "Mensagem corrigida")
        dialog.close()

    def test_toast_is_non_blocking_anchored_feedback(self):
        host = QWidget()
        host.resize(800, 500)
        field = QLineEdit(host)
        field.show()
        host.show()
        field.setFocus()
        self.application.processEvents()
        toast = ToastBanner("Configurações salvas.", host, kind="success")
        closed = []
        toast.closed.connect(lambda: closed.append(True))

        toast.show_anchored(duration_ms=0)
        self.application.processEvents()
        self.assertTrue(toast.isVisible())
        self.assertEqual(toast.focusPolicy(), Qt.NoFocus)
        self.assertEqual(toast.property("toastKind"), "success")
        self.assertGreater(toast.pos().x(), host.width() // 2)
        self.assertTrue(field.hasFocus())
        toast.dismiss()
        self.assertEqual(closed, [True])
        host.close()
        self.application.processEvents()

    def test_data_toolbar_exposes_filters_count_without_density_control(self):
        toolbar = DataToolbar(
            search_placeholder="Pesquisar documentos",
            primary_text="Atualizar",
        )
        filter_states = []
        toolbar.filtersToggled.connect(filter_states.append)

        toolbar.set_count("18 resultados")
        toolbar.set_filter_count(2)
        toolbar.filter_button.click()

        self.assertEqual(toolbar.counter.text(), "18 resultados")
        self.assertEqual(toolbar.filter_button.text(), "Filtros · 2")
        self.assertEqual(filter_states, [True])
        self.assertFalse(hasattr(toolbar, "density_button"))
        self.assertFalse(hasattr(toolbar, "densityChanged"))
        self.assertIn("Mostrar ou ocultar", toolbar.filter_button.toolTip())
        toolbar.close()

    def test_vr_controls_honor_minimum_target_and_reduced_motion(self):
        previous = self.application.property("vr_reduce_motion")
        self.application.setProperty("vr_reduce_motion", False)
        button = AnimatedVrFlowButton()
        frame = VrComposerGlowFrame()
        try:
            self.assertGreaterEqual(button.width(), 32)
            self.assertGreaterEqual(button.height(), 32)
            button.set_compact(True)
            self.assertGreaterEqual(button.width(), 32)
            self.assertGreaterEqual(button.height(), 32)

            frame.set_mode("ultra")
            self.application.processEvents()
            self.assertEqual(frame._phase_animation.loopCount(), 1)
            self.assertEqual(
                frame._phase_animation.state(), QAbstractAnimation.Running
            )
            frame.set_reduced_motion(True)
            self.assertEqual(
                frame._phase_animation.state(), QAbstractAnimation.Stopped
            )

            button.set_reduced_motion(True)
            button.setChecked(False)
            button.setChecked(True)
            self.assertEqual(
                button._glow_animation.state(), QAbstractAnimation.Stopped
            )
        finally:
            frame.close()
            button.close()
            self.application.setProperty("vr_reduce_motion", previous)

    def test_data_content_stack_has_content_empty_and_static_loading_states(self):
        content = QWidget()
        stack = DataContentStack(
            content,
            empty_title="Nenhum resultado",
            empty_message="Ajuste os filtros.",
            empty_action="Limpar filtros",
        )
        stack.set_state("loading")
        self.assertIs(stack.currentWidget(), stack.loading_state)
        self.assertEqual(
            len(stack.loading_state.findChildren(QWidget, "loadingSkeletonBar")),
            6,
        )
        stack.set_state("empty")
        self.assertIs(stack.currentWidget(), stack.empty_state)
        self.assertEqual(stack.empty_state.action_button.text(), "Limpar filtros")
        stack.set_state("content")
        self.assertIs(stack.currentWidget(), content)
        stack.close()

    def test_pagination_bar_keeps_range_and_navigation_semantics_together(self):
        pagination = PaginationBar()
        pagination.set_page(
            offset=100,
            page_size=100,
            visible_count=37,
            total=237,
        )

        self.assertEqual(pagination.page_label.text(), "Página 2 de 3")
        self.assertEqual(pagination.range_label.text(), "Exibindo 101–137 de 237")
        self.assertTrue(pagination.previous_button.isEnabled())
        self.assertTrue(pagination.next_button.isEnabled())
        pagination.close()

    def test_vr_mode_popup_explains_and_emits_independent_states(self):
        anchor = ProjectScopeButton()
        popup = VrModePopup(anchor)
        base_states = []
        modes = []
        popup.vrEnabledChanged.connect(base_states.append)
        popup.modeSelected.connect(modes.append)
        popup.set_state(
            vr_enabled=True,
            mode="standard",
            strategy="parallel",
            model_count=3,
        )

        self.assertTrue(popup.base_row.property("selected"))
        self.assertTrue(popup._mode_rows["standard"].property("selected"))
        self.assertIn("estratégia paralela", popup.summary.text())
        self.assertIn("3 modelo(s)", popup.summary.text())

        popup._toggle_base("base")
        popup._select_mode("ultra")
        self.assertEqual(base_states, [False])
        self.assertEqual(modes, ["ultra"])
        popup.close()
        anchor.close()


if __name__ == "__main__":
    unittest.main()
