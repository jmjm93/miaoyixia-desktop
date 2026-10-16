from app.i18n import tr
"""Application options, separate from the language of an existing capture."""
from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout


class OptionsDialog(QDialog):
    def __init__(self, language="zh", parent=None, user_language="en"):
        super().__init__(parent)
        self.setWindowTitle("Options")
        self.setMinimumWidth(360)
        self.setStyleSheet("QDialog { background: #151A22; } QLabel { color: #E6EAF2; }"
                           "QComboBox { padding: 7px; } QPushButton { padding: 6px 14px; }")
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.addWidget(QLabel(tr("Text language for new captures")))
        self.language_choice = QComboBox()
        self.language_choice.addItem("Chinese · 中文", "zh")
        self.language_choice.addItem("Japanese · 日本語", "ja")
        self.language_choice.setCurrentIndex(self.language_choice.findData(language))
        self.language_choice.setAccessibleName("Text language for new captures")
        layout.addWidget(self.language_choice)
        hint = QLabel(tr("Applies to new captures and pinned regions.\nAn existing region keeps its current language."))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addWidget(QLabel(tr("User language")))
        self.user_language_choice = QComboBox()
        self.user_language_choice.addItem("English", "en")
        self.user_language_choice.addItem("Español", "es")
        self.user_language_choice.setCurrentIndex(self.user_language_choice.findData(user_language))
        layout.addWidget(self.user_language_choice)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def language(self):
        return self.language_choice.currentData()

    @property
    def user_language(self):
        return self.user_language_choice.currentData()
