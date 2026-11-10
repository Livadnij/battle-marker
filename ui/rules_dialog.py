"""Editor for the marker rules, with every badge text scans have seen."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QMessageBox, QPushButton, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from events.rules import SOURCES, Rule, find_rule, rule_problems
from markers.icons import NAMED_ICONS
from storage.rules import list_rules, replace_rules, seen_labels
from ui.common import item, table
from ui.player.icons import icon_pixmap

RULE_COLUMNS = ["On", "Name", "Match text", "Source", "Icon", "Priority"]
SEEN_COLUMNS = ["Source", "Text", "Badges", "Picked by"]
ICON_CHOICES = NAMED_ICONS + [f"steam_{n}" for n in range(100)]
DIALOG_SIZE = (1000, 700)
UPDATE_DELAY_MS = 150  # edits in quick succession refresh the seen texts once


class RulesDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Marker rules")
        self.resize(*DIALOG_SIZE)

        self.rules_table = QTableWidget(0, len(RULE_COLUMNS))
        self.rules_table.setHorizontalHeaderLabels(RULE_COLUMNS)
        self.rules_table.verticalHeader().setVisible(False)
        self.rules_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.rules_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.rules_table.itemChanged.connect(lambda _: self._schedule_update())

        # Every edit restarts this timer, so typing or clicking quickly refreshes once.
        self.update_timer = QTimer(self)
        self.update_timer.setSingleShot(True)
        self.update_timer.setInterval(UPDATE_DELAY_MS)
        self.update_timer.timeout.connect(self._update_seen)

        add = QPushButton("Add rule")
        add.clicked.connect(lambda: self._add_row(Rule("", "", "tag", "steam_marker", 0)))
        remove = QPushButton("Remove selected")
        remove.clicked.connect(self._remove_selected)
        rule_buttons = QHBoxLayout()
        rule_buttons.addWidget(add)
        rule_buttons.addWidget(remove)
        rule_buttons.addStretch()
        hint = QLabel("A badge becomes a marker when its text contains the match text. "
                      "When several rules match, the highest priority picks the icon.")
        hint.setWordWrap(True)
        rules_group = QGroupBox("Rules")
        rules_layout = QVBoxLayout(rules_group)
        rules_layout.addWidget(hint)
        rules_layout.addWidget(self.rules_table, 1)
        rules_layout.addLayout(rule_buttons)

        self.seen_table = table(SEEN_COLUMNS, stretch_column=1)
        self.seen_table.cellDoubleClicked.connect(lambda row, _: self._add_from_seen(row))
        add_seen = QPushButton("Add as rule")
        add_seen.clicked.connect(self._add_selected_seen)
        seen_buttons = QHBoxLayout()
        seen_buttons.addStretch()
        seen_buttons.addWidget(add_seen)
        seen_group = QGroupBox("Badge texts seen in your scans")
        seen_layout = QVBoxLayout(seen_group)
        seen_layout.addWidget(self.seen_table, 1)
        seen_layout.addLayout(seen_buttons)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(rules_group)
        splitter.addWidget(seen_group)
        splitter.setSizes([380, 300])

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)
        layout.addWidget(buttons)

        self.seen = seen_labels()
        self.picked_items: list[QTableWidgetItem] = []
        self._fill_seen()
        for rule in list_rules():
            self._add_row(rule)
        self._fit_columns()
        self._update_seen()

    # ---- rules table ----------------------------------------------------

    def _add_row(self, rule: Rule) -> None:
        row = self.rules_table.rowCount()
        self.rules_table.blockSignals(True)
        self.rules_table.insertRow(row)
        on = QTableWidgetItem()
        on.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        on.setCheckState(Qt.CheckState.Checked if rule.enabled else Qt.CheckState.Unchecked)
        self.rules_table.setItem(row, 0, on)
        self.rules_table.setItem(row, 1, QTableWidgetItem(rule.name))
        self.rules_table.setItem(row, 2, QTableWidgetItem(rule.match))

        source = QComboBox()
        source.addItems(list(SOURCES))
        source.setCurrentText(rule.source)
        source.currentTextChanged.connect(lambda _: self._schedule_update())
        self.rules_table.setCellWidget(row, 3, source)

        icon = QComboBox()
        text_color = self.palette().color(QPalette.ColorRole.Text)
        for name in ICON_CHOICES:
            icon.addItem(icon_pixmap(name, 18, text_color), name)
        icon.setCurrentText(rule.icon if rule.icon in ICON_CHOICES else "steam_marker")
        self.rules_table.setCellWidget(row, 4, icon)

        priority = QSpinBox()
        priority.setRange(0, 1000)
        priority.setValue(rule.priority)
        priority.valueChanged.connect(lambda _: self._schedule_update())
        self.rules_table.setCellWidget(row, 5, priority)
        self.rules_table.blockSignals(False)
        self._schedule_update()

    def _remove_selected(self) -> None:
        rows = sorted({i.row() for i in self.rules_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.rules_table.removeRow(row)
        self._schedule_update()

    def _rules(self) -> list[Rule]:
        rules = []
        for row in range(self.rules_table.rowCount()):
            name = self.rules_table.item(row, 1).text().strip()
            match = self.rules_table.item(row, 2).text().strip()
            rules.append(Rule(
                name=name or match,
                match=match,
                source=self.rules_table.cellWidget(row, 3).currentText(),
                icon=self.rules_table.cellWidget(row, 4).currentText(),
                priority=self.rules_table.cellWidget(row, 5).value(),
                enabled=self.rules_table.item(row, 0).checkState() == Qt.CheckState.Checked,
            ))
        return rules

    # ---- seen texts -----------------------------------------------------

    def _fill_seen(self) -> None:
        """Fills the seen table once. Later edits only change the Picked by column."""
        self.seen_table.setRowCount(len(self.seen))
        for row, seen in enumerate(self.seen):
            self.seen_table.setItem(row, 0, item(seen.kind))
            self.seen_table.setItem(row, 1, item(seen.label))
            self.seen_table.setItem(row, 2, item(str(seen.count), align_right=True))
            picked = item("")
            self.seen_table.setItem(row, 3, picked)
            self.picked_items.append(picked)

    def _fit_columns(self) -> None:
        """Sizes the columns to their contents once. Measuring on every edit is what made it slow."""
        for t, stretch in ((self.rules_table, 2), (self.seen_table, 1)):
            header = t.horizontalHeader()
            for col in range(t.columnCount()):
                if col != stretch:
                    t.resizeColumnToContents(col)
                    header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        # Rule names change while editing, give Picked by room for them.
        self.seen_table.setColumnWidth(3, max(self.seen_table.columnWidth(3), 160))

    def _schedule_update(self) -> None:
        self.update_timer.start()

    def _update_seen(self) -> None:
        rules = [r for r in self._rules() if r.match]
        for seen, picked in zip(self.seen, self.picked_items):
            rule = find_rule(rules, seen.kind, seen.label)
            text = rule.name if rule else ""
            if picked.text() != text:
                picked.setText(text)

    def _add_from_seen(self, row: int) -> None:
        if row < len(self.seen):
            seen = self.seen[row]
            self._add_row(Rule(seen.label, seen.label, seen.kind, "steam_marker", 0))
            self.rules_table.scrollToBottom()

    def _add_selected_seen(self) -> None:
        for row in sorted({i.row() for i in self.seen_table.selectedIndexes()}):
            self._add_from_seen(row)

    # ---- saving ---------------------------------------------------------

    def _save(self) -> None:
        rules = self._rules()
        problems = [p for r in rules for p in rule_problems(r)]
        if problems:
            QMessageBox.warning(self, "Rules not saved", "\n".join(problems))
            return
        replace_rules(rules)
        self.accept()
