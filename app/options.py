from app.i18n import tr
"""Application options, separate from the language of an existing capture."""
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout,
    QWidget, QTabWidget, QFormLayout, QLineEdit, QCheckBox, QTableWidget,
    QTableWidgetItem, QPushButton, QHBoxLayout, QHeaderView, QScrollArea)
from core.config import load, save_options
from core.anki.fields import TOKENS


class AnkiSettings(QWidget):
    def __init__(self, config, japanese=False):
        super().__init__()
        self.japanese = japanese
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self.enabled = QCheckBox(tr("Enable Anki export"))
        self.enabled.setChecked(config.enabled)
        form.addRow(self.enabled)
        self.inputs = {}
        for key, label in (("origin", "AnkiConnect address"), ("deck", "Deck"),
                           ("model", "Note type"), ("tags", "Tags")):
            edit = QLineEdit(getattr(config, key))
            edit.setAccessibleName(tr(label))
            self.inputs[key] = edit
            form.addRow(tr(label), edit)
        self.choices = {}
        choice_values = {
            "audio": [("Recordings, then speech", "auto"), ("Recordings only", "recording"),
                      ("Speech only", "voice"), ("Off", "off")],
            "tts_service": [("Edge TTS", "edge"), ("Google", "google"), ("Off", "off")] if japanese else
                           [("Google", "google"), ("Baidu", "baidu"), ("Off", "off")],
            "script": [("As read", "as-read"), ("Simplified", "simplified"), ("Traditional", "traditional")],
        }
        labels = {"audio": "Audio", "tts_service": "Speech service", "script": "Export script"}
        for key, values in choice_values.items():
            if japanese and key == "script":
                continue
            combo = QComboBox()
            for label, value in values:
                combo.addItem(tr(label), value)
            current = getattr(config, key)
            if combo.findData(current) < 0:
                combo.addItem(current, current)
            combo.setCurrentIndex(combo.findData(current))
            combo.setAccessibleName(tr(labels[key]))
            self.choices[key] = combo
            form.addRow(tr(labels[key]), combo)
        if japanese:
            voice = QLineEdit(config.tts_voice)
            voice.setPlaceholderText("ja-JP-NanamiNeural")
            self.inputs["tts_voice"] = voice
            form.addRow(tr("Speech voice"), voice)
        layout.addWidget(QLabel(tr("Fields: Anki field name → content")))
        self.fields = QTableWidget(0, 2)
        self.fields.setHorizontalHeaderLabels([tr("Field name"), tr("Content")])
        self.fields.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.fields.setMinimumHeight(180)
        layout.addWidget(self.fields)
        for name, token in config.fields.items():
            self.add_field(name, token)
        buttons = QHBoxLayout()
        add = QPushButton(tr("Add field"))
        remove = QPushButton(tr("Remove field"))
        add.clicked.connect(lambda: self.add_field())
        remove.clicked.connect(self.remove_field)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch()
        layout.addLayout(buttons)
        note = QLabel(tr("Settings do not modify existing Anki notes or templates."))
        note.setWordWrap(True)
        layout.addWidget(note)

    def add_field(self, name="", token="none"):
        row = self.fields.rowCount()
        self.fields.insertRow(row)
        self.fields.setItem(row, 0, QTableWidgetItem(name))
        combo = QComboBox()
        for item in TOKENS:
            combo.addItem(tr(item.label), item.id)
        if combo.findData(token) < 0:
            combo.addItem(token, token)
        combo.setCurrentIndex(combo.findData(token))
        self.fields.setCellWidget(row, 1, combo)

    def remove_field(self):
        row = self.fields.currentRow()
        if row >= 0:
            self.fields.removeRow(row)

    def values(self):
        from urllib.parse import urlsplit
        values = {key: edit.text().strip() for key, edit in self.inputs.items()}
        address = urlsplit(values["origin"])
        if address.scheme not in ("http", "https") or not address.hostname:
            raise ValueError(tr("Enter a valid AnkiConnect HTTP address."))
        if not values["deck"] or not values["model"]:
            raise ValueError(tr("Deck and note type cannot be empty."))
        values.update({key: combo.currentData() for key, combo in self.choices.items()})
        mapping = {}
        for row in range(self.fields.rowCount()):
            name = self.fields.item(row, 0).text().strip()
            if not name or name in mapping:
                raise ValueError(tr("Field names must be nonempty and unique."))
            mapping[name] = self.fields.cellWidget(row, 1).currentData()
        if not mapping:
            raise ValueError(tr("Add at least one field."))
        values.update(enabled=self.enabled.isChecked(), fields=mapping)
        return values


class OptionsDialog(QDialog):
    def __init__(self, language="zh", parent=None, user_language="en", config=None):
        super().__init__(parent)
        self.setWindowTitle("Options")
        self.config = config or load()
        self.setMinimumWidth(570)
        self.resize(620, 650)
        self.setStyleSheet("QDialog, QTabWidget::pane, QWidget#generalOptions, QScrollArea, QScrollArea > QWidget > QWidget { background: #151A22; }"
                           "QLabel, QCheckBox { color: #E6EAF2; }"
                           "QLineEdit, QComboBox, QTableWidget { background: #202938; color: #E6EAF2; padding: 5px; }"
                           "QTabBar::tab, QPushButton { background: #29364A; color: #E6EAF2; padding: 6px 14px; }"
                           "QTabBar::tab:selected { background: #3D5071; }")
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        general = QWidget()
        general.setObjectName("generalOptions")
        tabs.addTab(general, tr("General"))
        general_layout = QVBoxLayout(general)
        outer = layout
        layout = general_layout
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
        layout.addStretch()
        self.anki_chinese = AnkiSettings(self.config.anki)
        self.anki_japanese = AnkiSettings(self.config.anki_japanese, japanese=True)
        for title, panel in (("Anki · Chinese", self.anki_chinese), ("Anki · Japanese", self.anki_japanese)):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(panel)
            tabs.addTab(scroll, tr(title))
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #F3A0A0;")
        outer.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def accept(self):
        try:
            save_options(self.config.path, {"session": {"language": self.language, "user_language": self.user_language},
                "anki": self.anki_chinese.values(), "anki_japanese": self.anki_japanese.values()})
        except (OSError, ValueError) as exc:
            self.error.setText(str(exc))
            return
        super().accept()

    @property
    def language(self):
        return self.language_choice.currentData()

    @property
    def user_language(self):
        return self.user_language_choice.currentData()
