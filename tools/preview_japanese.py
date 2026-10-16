"""Render the Japanese session UI for manual inspection."""
import os
import sys
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from app.options import OptionsDialog
from app.result import ResultWindow
from app.worker import Reading
from core.reading import read_line
from app.i18n import set_language, localize

spanish = "--spanish" in sys.argv
set_language("es" if spanish else "en")

app = QApplication([])
QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
QFontDatabase.addApplicationFont("C:/Windows/Fonts/YuGothM.ttc")
app.setFont(QFont("Yu Gothic", 10))
directory = Path(__file__).resolve().parents[1] / ".pytest_cache"
picker = OptionsDialog("ja", user_language="es" if spanish else "en")
localize(picker)
picker.show()
app.processEvents()
picker.grab().save(str(directory / ("options-spanish.png" if spanish else "options.png")))
window = ResultWindow("ja")
window.set_anki_enabled(True)
window.set_translation_enabled(True, "es" if spanish else "en")
assert window._anki_enabled
sentence = "昨日ご飯を食べました。"
reading = Reading(sentence, read_line(sentence, "ja", "es" if spanish else "en"), "horizontal", False, (), 100, 110)
window.show_reading(reading)
window.select_token(3)
window.show()
localize(window)
app.processEvents()
window.grab().save(str(directory / ("japanese-spanish.png" if spanish else "japanese-result.png")))
window.close()
picker.close()
