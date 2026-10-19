#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""开关机初始化确认对话框"""

import os
import json

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                              QLineEdit, QPushButton, QGroupBox, QGridLayout,
                              QFileDialog, QScrollArea, QWidget, QMessageBox)


class CountInitConfirmDialog(QDialog):
    """开关机初始化确认对话框

    功能：
    1. 根据选中的设备类型分组显示
    2. 显示每组需要推送的文件及远程路径
    3. 允许用户自定义本地文件路径（默认为tools目录）
    """

    def __init__(self, selected_devices_info, default_tool_path, parent=None):
        """
        参数:
            selected_devices_info: 选中的设备信息列表 [{id, ip, password, ...}, ...]
            default_tool_path: 默认工具文件路径
            parent: 父窗口
        """
        super().__init__(parent)
        self.selected_devices_info = selected_devices_info
        self.default_tool_path = default_tool_path
        self.file_paths = {}  # 存储用户自定义的文件路径 {文件名: 本地路径}

        self.setWindowTitle("开关机初始化确认")
        self.setMinimumWidth(700)
        self.setMinimumHeight(500)

        self._group_by_config()
        self._init_ui()

    def _group_by_config(self):
        """从 device_info.json 动态加载配置并按配置分组"""
        from device_config import get_init_grouped_configs

        # 收集所有选中设备的型号前缀
        device_types = []
        for device_info in self.selected_devices_info:
            device_id = device_info['id']
            dev_type_prefix = device_id.split('-')[0] if '-' in device_id else device_id
            device_types.append(dev_type_prefix)

        # 从 device_info.json 加载分组配置
        self.grouped_configs = get_init_grouped_configs(device_types)

    def _init_ui(self):
        """初始化UI界面"""
        layout = QVBoxLayout(self)

        # 标题说明
        title_label = QLabel(f"已选中 {len(self.selected_devices_info)} 台设备，按类型分组如下：")
        title_label.setStyleSheet("font-weight: bold; font-size: 14px; padding: 5px;")
        layout.addWidget(title_label)

        # 创建滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)

        # 为每个分组创建显示区域
        for config_sig, group_data in self.grouped_configs.items():
            config = group_data["config"]
            devices = group_data["devices"]
            chip = group_data.get("chip_model", "")
            version = group_data.get("system_version", "")

            if config:
                title = f"主控: {chip} | 系统: {version} | ({len(devices)}台)"
            else:
                title = f"设备: {', '.join(devices)} (无初始化配置)"

            group_box = QGroupBox(title)
            group_layout = QGridLayout(group_box)

            if config:
                devices_label = QLabel("设备型号: " + ", ".join(devices))
                devices_label.setWordWrap(True)
                group_layout.addWidget(devices_label, 0, 0, 1, 3)

                # 显示需要推送的文件
                if config.get("files"):
                    file_header = QLabel("需要推送的文件:")
                    file_header.setStyleSheet("font-weight: bold; padding-top: 5px;")
                    group_layout.addWidget(file_header, 1, 0, 1, 3)

                    for row_idx, file_info in enumerate(config["files"], start=2):
                        filename = file_info["local"]
                        remote_path = file_info["remote"]
                        desc = file_info["desc"]
                        file_row = 2 + (row_idx - 2) * 2  # 每个文件占2行

                        # 文件描述
                        desc_label = QLabel(f"{desc} ({filename})")
                        group_layout.addWidget(desc_label, file_row, 0)

                        # 远程路径显示
                        remote_label = QLabel(f"\u2192 {remote_path}")
                        remote_label.setStyleSheet("color: gray;")
                        group_layout.addWidget(remote_label, file_row, 1)

                        # 本地文件路径选择（下一行）
                        path_edit = QLineEdit()
                        default_path = os.path.join(self.default_tool_path, filename)
                        path_edit.setText(default_path)
                        path_edit.setMinimumWidth(350)
                        self.file_paths[filename] = default_path
                        group_layout.addWidget(path_edit, file_row + 1, 0, 1, 2)

                        # 浏览按钮（下一行）
                        browse_btn = QPushButton("\u6d4f\u89c8...")
                        browse_btn.clicked.connect(lambda checked, edit=path_edit, fname=filename:
                                                  self._on_browse_file(edit, fname))
                        group_layout.addWidget(browse_btn, file_row + 1, 3)

                # 显示额外命令
                extra_commands = config.get("extra_commands", [])
                if extra_commands:
                    files_count = len(config.get("files", []))
                    row_offset = 2 + files_count * 2  # 每个文件占2行
                    extra_label = QLabel("额外命令:")
                    extra_label.setStyleSheet("font-weight: bold; padding-top: 5px;")
                    group_layout.addWidget(extra_label, row_offset, 0, 1, 4)
                    for cmd_idx, cmd in enumerate(extra_commands):
                        cmd_text = QLabel(f"  {cmd}")
                        cmd_text.setStyleSheet("color: #666;")
                        group_layout.addWidget(cmd_text, row_offset + 1 + cmd_idx, 0, 1, 4)

                # 显示flag文件路径
                flag_path = config.get("flag_path", "")
                if flag_path:
                    extra_count = len(config.get("extra_commands", []))
                    files_count = len(config.get("files", []))
                    flag_row = 2 + files_count * 2 + (1 + extra_count if extra_commands else 0)  # 每个文件占2行
                    flag_label = QLabel(f"Flag文件路径: {flag_path}")
                    flag_label.setStyleSheet("color: blue; padding-top: 5px;")
                    group_layout.addWidget(flag_label, flag_row, 0, 1, 4)
            else:
                no_config_label = QLabel(f"设备: {', '.join(devices)} (无初始化配置)")
                no_config_label.setStyleSheet("color: red; padding: 5px;")
                group_layout.addWidget(no_config_label, 0, 0, 1, 4)

            scroll_layout.addWidget(group_box)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        # 操作说明
        info_label = QLabel("提示: 可点击\u201c浏览...\u201d按钮自定义本地文件路径，默认使用tools目录下的文件")
        info_label.setStyleSheet("color: gray; padding: 5px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # 按钮区域
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        confirm_btn = QPushButton("确认初始化")
        confirm_btn.setMinimumWidth(120)
        confirm_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px;")
        confirm_btn.clicked.connect(self._on_confirm)

        cancel_btn = QPushButton("取消")
        cancel_btn.setMinimumWidth(120)
        cancel_btn.clicked.connect(self.reject)

        btn_layout.addWidget(confirm_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _on_browse_file(self, path_edit, filename):
        """浏览选择文件"""
        current_path = path_edit.text()
        initial_dir = os.path.dirname(current_path) if os.path.exists(current_path) else self.default_tool_path

        file_path, _ = QFileDialog.getOpenFileName(
            self, f"选择 {filename} 文件", initial_dir,
            f"{filename} ({filename});;All Files (*)"
        )

        if file_path:
            path_edit.setText(file_path)
            self.file_paths[filename] = file_path

    def _on_confirm(self):
        """确认按钮点击"""
        # 从UI重新获取所有路径
        for i in range(self.layout().count()):
            item = self.layout().itemAt(i)
            if item.widget() and isinstance(item.widget(), QScrollArea):
                scroll = item.widget()
                scroll_content = scroll.widget()
                if scroll_content:
                    self._update_paths_from_layout(scroll_content.layout())

        # 验证文件是否存在
        missing_files = []
        for filename, filepath in self.file_paths.items():
            if not os.path.exists(filepath):
                missing_files.append(f"{filename}: {filepath}")

        if missing_files:
            QMessageBox.warning(self, "文件不存在",
                              f"以下文件不存在，请检查路径:\n\n" + "\n".join(missing_files))
            return

        self.accept()

    def _update_paths_from_layout(self, layout):
        """从布局中更新文件路径"""
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item.widget():
                widget = item.widget()
                if isinstance(widget, QGroupBox):
                    # 查找GroupBox内的QLineEdit
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
                # 从路径中提取文件名
                filename = os.path.basename(path_text)
                if filename:
                    self.file_paths[filename] = path_text

    def get_file_paths(self):
        """获取用户自定义的文件路径"""
        return self.file_paths.copy()

    def get_grouped_devices(self):
        """获取分组后的设备信息（兼容旧接口）"""
        result = {}
        for config_sig, group_data in self.grouped_configs.items():
            result[config_sig] = group_data["devices"]
        return result
