from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QMessageBox, QVBoxLayout

from .record_form import RecordForm


class RecordDialog(QDialog):
    def __init__(self, record: dict | None = None, parent=None):
        super().__init__(parent)
        self.is_new = record is None
        self.setWindowTitle("补录数据" if self.is_new else "修改历史数据")
        self.setMinimumWidth(610)
        layout = QVBoxLayout(self)
        self.form = RecordForm()
        if record is not None:
            self.form.set_payload(record)
        layout.addWidget(self.form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText(
            "保存补录" if self.is_new else "保存修改"
        )
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._accept_checked)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept_checked(self) -> None:
        if not self.form.issue.text().strip():
            QMessageBox.warning(self, "无法保存", "期号不能为空。")
            return
        self.accept()

    def payload(self) -> dict:
        return self.form.payload()
