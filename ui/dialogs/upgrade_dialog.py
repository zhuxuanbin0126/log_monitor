#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""发送节目确认对话框"""

import os

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                              QLineEdit, QPushButton, QGroupBox, QGridLayout,
                              QFileDialog, QScrollArea, QWidget, QMessageBox)


class UpgradeConfirmDialog(QDialog):
    """发送节目确认对话框"""

    def __init__(self, selected_devices_info, default_program_path, parent=None):
        super().__init__(parent)
        self.selected_devices_info = selected_devices_info
        self.default_program_path = default_program_path
        self.file_paths = {}

        self.setWindowTitle("发送节目确认")
        self.setMinimumWidth(700)
        self.setMinimumHeight(500)

        self._group_by_config()
        self._init_ui()

    def _group_by_config(self):
        """按配置分组设备"""
        from device_config import get_upgrade_grouped_configs

        device_types = []
        for device_info in self.selected_devices_info:
            device_id = device_info['id']
            dev_type_prefix = device_id.split('-')[0] if '-' in device_id else device_id
            device_types.append(dev_type_prefix)

        self.grouped_configs = get_upgrade_grouped_configs(device_types)

    def _init_ui(self):
        """初始化UI界面"""
        layout = QVBoxLayout(self)

        title_label = QLabel(f"已选中 {len(self.selected_devices_info)} 台设备，按配置分组如下：")
        title_label.setStyleSheet("font-weight: bold; font-size: 14px; padding: 5px;")
        layout.addWidget(title_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)

        for config_sig, group_data in self.grouped_configs.items():
            config = group_data["config"]
            devices = group_data["devices"]
            sys_type = group_data.get("system_type", "")

            if config:
                title = f"{sys_type} ({len(devices)}台)"
            else:
                title = f"设备: {', '.join(devices)} (无发送节目配置)"

            group_box = QGroupBox(title)
            group_layout = QGridLayout(group_box)

            if config:
                devices_label = QLabel("设备型号: " + ", ".join(devices))
                devices_label.setWordWrap(True)
                group_layout.addWidget(devices_label, 0, 0, 1, 4)

                row = 1
                for dev_type in devices:
                    program_name = config["program_name"].replace("{model}", dev_type)
                    remote_dir = config["remote_dir"]
                    restart_cmd = config.get("restart_cmd", "")
                    pre_commands = config.get("pre_commands", [])

                    prog_label = QLabel(f"节目文件 ({dev_type}):")
                    group_layout.addWidget(prog_label, row, 0)

                    remote_label = QLabel(f"-> {remote_dir}/{program_name}")
                    remote_label.setStyleSheet("color: gray;")
                    group_layout.addWidget(remote_label, row, 1)

                    # 本地文件路径（下一行）
                    path_edit = QLineEdit()
                    default_path = os.path.join(self.default_program_path, program_name)
                    path_edit.setText(default_path)
                    path_edit.setMinimumWidth(350)
                    self.file_paths[dev_type] = default_path
                    group_layout.addWidget(path_edit, row + 1, 0, 1, 2)

                    # 浏览按钮（下一行）
                    browse_btn = QPushButton("\u6d4f\u89c8...")
                    browse_btn.clicked.connect(lambda checked, edit=path_edit, dt=dev_type:
                                              self._on_browse_file(edit, dt, program_name))
                    group_layout.addWidget(browse_btn, row + 1, 3)

                    row += 2  # 每个设备占2行

                if pre_commands:
                    pre_label = QLabel("\u524d\u7f6e\u547d\u4ee4:")
                    pre_label.setStyleSheet("font-weight: bold; padding-top: 5px;")
                    group_layout.addWidget(pre_label, row, 0, 1, 4)
                    row += 1
                    for cmd in pre_commands:
                        cmd_text = QLabel(f"  {cmd}")
                        cmd_text.setStyleSheet("color: #666;")
                        group_layout.addWidget(cmd_text, row, 0, 1, 4)
                        row += 1

                restart_label = QLabel(f"\u91cd\u542f\u547d\u4ee4: {restart_cmd}")
                restart_label.setStyleSheet("color: blue; padding-top: 5px;")
                group_layout.addWidget(restart_label, row, 0, 1, 4)
            else:
                no_config_label = QLabel("\u672a\u5728 device_info.json \u4e2d\u627e\u5230\u6b64\u8bbe\u5907\u7684\u53d1\u9001\u8282\u76ee\u914d\u7f6e")
                no_config_label.setStyleSheet("color: red; padding: 5px;")
                group_layout.addWidget(no_config_label, 1, 0, 1, 4)

            scroll_layout.addWidget(group_box)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        info_label = QLabel("\u63d0\u793a: \u914d\u7f6e\u6765\u6e90\u4e8e device_info.json, \u53ef\u70b9\u51fb\u201c\u6d4f\u89c8...\u201d\u6309\u94ae\u81ea\u5b9a\u4e49\u672c\u5730\u8282\u76ee\u6587\u4ef6\u8def\u5f84")
        info_label.setStyleSheet("color: gray; padding: 5px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        confirm_btn = QPushButton("\u786e\u8ba4\u53d1\u9001")
        confirm_btn.setMinimumWidth(120)
        confirm_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px;")
        confirm_btn.clicked.connect(self._on_confirm)

        cancel_btn = QPushButton("\u53d6\u6d88")
        cancel_btn.setMinimumWidth(120)
        cancel_btn.clicked.connect(self.reject)

        btn_layout.addWidget(confirm_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _on_browse_file(self, path_edit, dev_type, program_name):
        """浏览选择文件"""
        current_path = path_edit.text()
        initial_dir = os.path.dirname(current_path) if os.path.exists(current_path) else self.default_program_path

        file_path, _ = QFileDialog.getOpenFileName(
            self, f"选择 {dev_type} 的节目文件", initial_dir,
            "TAR.GZ Files (*.tar.gz);;All Files (*)"
        )

        if file_path:
            path_edit.setText(file_path)
            self.file_paths[dev_type] = file_path

    def _on_confirm(self):
        """确认按钮点击"""
        for i in range(self.layout().count()):
            item = self.layout().itemAt(i)
            if item.widget() and isinstance(item.widget(), QScrollArea):
                scroll = item.widget()
                scroll_content = scroll.widget()
                if scroll_content:
                    self._update_paths_from_layout(scroll_content.layout())

        missing_files = []
        for dev_type, filepath in self.file_paths.items():
            if not os.path.exists(filepath):
                missing_files.append(f"{dev_type}: {filepath}")

        if missing_files:
            QMessageBox.warning(self, "文件不存在",
                              f"以下节目文件不存在，请检查路径:\n\n" + "\n".join(missing_files))
            return

        self.accept()

    def _update_paths_from_layout(self, layout):
        """从布局中更新文件路径"""
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item.widget():
                widget = item.widget()
                if isinstance(widget, QGroupBox):
                    group_layout = widget.layout()
                    if group_layout:
                        self._extract_paths_from_grid(group_layout)
            elif item.layout():
                self._update_paths_from_layout(item.layout())

    def _extract_paths_from_grid(self, grid_layout):
        """从网格布局中提取文件路径"""
        for i in range(grid_layout.count()):
            item = grid_layout.itemAt(i)
            if item.widget() and isinstance(item.widget(), QLineEdit):
                path_text = item.widget().text()
                filename = os.path.basename(path_text)
                if filename:
                    dev_type = filename.split('_')[0] if '_' in filename else filename
                    self.file_paths[dev_type] = path_text

    def get_file_paths(self):
        """获取用户自定义的文件路径"""
        return self.file_paths.copy()
