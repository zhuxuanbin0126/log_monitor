#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""清理历史数据对话框：选择清理范围 + 预览确切路径与文件清单。"""

from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QCheckBox, QDialog, QGroupBox, QHBoxLayout, QLabel,
                              QMessageBox, QPlainTextEdit, QPushButton,
                              QRadioButton, QVBoxLayout)

from service.history_cleaner import (
    ALL_SCOPES, DEFAULT_SCOPES, SCOPE_LABELS, build_plan, format_plan_preview,
)


class ClearHistoryDialog(QDialog):
    """清理历史数据：范围多选 + 设备范围单选 + 逐条预览 + 确认。

    - 默认只勾「监控基准数据」，设备范围默认「仅当前设备类型」；
    - 预览区列出**确切路径、文件数与文件清单**（每个条目最多列 5 个文件），
      确认前即可审计将要删除的内容。
    """

    def __init__(self, dev_type: str, parent=None):
        super().__init__(parent)
        self.dev_type = dev_type
        self._plan = []

        self.setWindowTitle("清理历史数据")
        self.setMinimumWidth(780)
        self.setMinimumHeight(580)

        self._init_ui()
        self._refresh_preview()

    def _init_ui(self):
        """构建界面。"""
        layout = QVBoxLayout(self)

        note = QLabel("提示：删除后不可恢复，请核对下方清单后再执行。")
        note.setStyleSheet("color: #c0392b; padding: 4px;")
        layout.addWidget(note)

        # 清理范围
        scope_box = QGroupBox("清理范围（可多选）")
        scope_layout = QVBoxLayout(scope_box)
        self.scope_checks = {}
        for scope in ALL_SCOPES:
            checkbox = QCheckBox(SCOPE_LABELS[scope])
            checkbox.setChecked(scope in DEFAULT_SCOPES)
            checkbox.stateChanged.connect(self._refresh_preview)
            self.scope_checks[scope] = checkbox
            scope_layout.addWidget(checkbox)
        layout.addWidget(scope_box)

        # 设备范围
        range_box = QGroupBox("设备范围")
        range_layout = QHBoxLayout(range_box)
        self.radio_current = QRadioButton(f"仅当前设备类型（{self.dev_type}）")
        self.radio_all = QRadioButton("全部型号")
        self.radio_current.setChecked(True)
        self.radio_current.toggled.connect(self._refresh_preview)
        range_layout.addWidget(self.radio_current)
        range_layout.addWidget(self.radio_all)
        range_layout.addStretch()
        layout.addWidget(range_box)

        # 预览
        layout.addWidget(QLabel("将要删除的内容（确切路径与文件清单）："))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(QFont("Consolas"))
        layout.addWidget(self.preview)

        # 按钮
        button_layout = QHBoxLayout()
        refresh_button = QPushButton("刷新预览")
        refresh_button.clicked.connect(self._refresh_preview)
        button_layout.addWidget(refresh_button)
        button_layout.addStretch()

        self.confirm_button = QPushButton("确认清理")
        self.confirm_button.setMinimumWidth(120)
        self.confirm_button.setStyleSheet(
            "background-color: #c0392b; color: white; padding: 6px;")
        self.confirm_button.clicked.connect(self._on_confirm)
        cancel_button = QPushButton("取消")
        cancel_button.setMinimumWidth(120)
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.confirm_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)

    def selected_scopes(self):
        """当前勾选的范围列表。"""
        return [scope for scope, checkbox in self.scope_checks.items()
                if checkbox.isChecked()]

    def include_all_types(self) -> bool:
        """是否清理全部型号（否则仅当前设备类型）。"""
        return self.radio_all.isChecked()

    def _refresh_preview(self, *_args):
        """按当前选择重建规划并刷新预览。"""
        self._plan = build_plan(self.dev_type, self.selected_scopes(),
                                self.include_all_types())
        self.preview.setPlainText(format_plan_preview(self._plan))
        self.confirm_button.setEnabled(bool(self._plan))

    def _on_confirm(self):
        """确认清理：无匹配项时提示并停留在对话框。"""
        if not self._plan:
            QMessageBox.information(self, "无可清理内容",
                                    "当前选择没有匹配到可清理的历史数据。")
            return
        self.accept()

    def plan(self):
        """当前规划（供调用方执行）。"""
        return list(self._plan)
