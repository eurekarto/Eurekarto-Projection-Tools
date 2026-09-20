# Copyright © 2026 Blanche Lambert / Eurêkarto
# SPDX-License-Identifier: GPL-2.0-or-later
"""Common dialog: parameter form, progress, log, and cooperative cancellation.

Processing runs on the GUI thread, so the feedback object pumps the event loop at
a fixed interval — often enough for the window to stay responsive and for Cancel
to be seen, rarely enough not to slow the work down.
"""
import time
from qgis.PyQt.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QDoubleSpinBox,
                                 QFormLayout, QLabel, QPlainTextEdit, QProgressBar, QVBoxLayout)
from qgis.core import QgsProcessingFeedback
from ..common import tr


class DialogFeedback(QgsProcessingFeedback):
    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
        self.errors = []
        self.last_pump = 0
        self.progressChanged.connect(self.update_progress)

    def pump(self):
        if time.monotonic() - self.last_pump > 0.05:
            self.last_pump = time.monotonic()
            QApplication.processEvents()

    def update_progress(self, value):
        self.dialog.progress.setValue(int(value))
        self.pump()

    def pushInfo(self, text):
        self.dialog.log.appendPlainText(text)
        self.pump()

    def reportError(self, error, fatalError=False):
        self.errors.append(error)
        self.pushInfo(error)

    def pushWarning(self, text):
        self.pushInfo(text)


class ToolDialog(QDialog):
    def __init__(self, parent, title, callback):
        super().__init__(parent)
        self.setWindowTitle(tr(title))
        self.resize(620, 530)
        self.callback = callback
        self.running = False
        self.feedback = None
        layout = QVBoxLayout(self)
        self.form = QFormLayout()
        layout.addLayout(self.form)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        role = QDialogButtonBox.ButtonRole.ActionRole
        self.run_button = self.buttons.addButton(tr('Run'), role)
        self.cancel_button = self.buttons.addButton(tr('Cancel'), role)
        self.cancel_button.setEnabled(False)
        self.buttons.rejected.connect(self.reject)
        self.run_button.clicked.connect(self.execute)
        self.cancel_button.clicked.connect(self.cancel)
        layout.addWidget(self.buttons)
        layout.addWidget(QLabel('© 2026 Blanche Lambert / Eurêkarto · GPL v2 or later'))

    def number(self, label, value, low, high, decimals=3):
        widget = QDoubleSpinBox()
        widget.setDecimals(decimals)
        widget.setRange(low, high)
        widget.setValue(value)
        self.form.addRow(tr(label), widget)
        return widget

    def execute(self):
        if self.running:
            return
        self.log.clear()
        self.progress.setValue(0)
        self.running = True
        self.feedback = DialogFeedback(self)
        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        for i in range(self.form.count()):
            widget = self.form.itemAt(i).widget()
            if widget:
                widget.setEnabled(False)
        try:
            self.callback(self)
        finally:
            self.running = False
            self.run_button.setEnabled(True)
            self.cancel_button.setEnabled(False)
            for i in range(self.form.count()):
                widget = self.form.itemAt(i).widget()
                if widget:
                    widget.setEnabled(True)
            self.update_controls()

    def update_controls(self):
        pass

    def cancel(self):
        if self.feedback:
            self.feedback.cancel()

    def reject(self):
        if self.running:
            self.cancel()
        else:
            super().reject()

    def closeEvent(self, event):
        if self.running:
            self.cancel()
            event.ignore()
        else:
            event.accept()
