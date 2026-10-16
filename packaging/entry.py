"""Desktop entry point and unattended verification for packaged Windows builds."""
import json
from pathlib import Path
import sys

if "--self-test" in sys.argv:
    # No Qt windows, collection writes, or external services. Exercise shipped assets only.
    from PIL import Image
    import socket
    def offline(*args, **kwargs):
        raise RuntimeError('Packaged self-test must not use the network')
    socket.socket.connect = offline
    socket.socket.connect_ex = offline
    from core.reading import read_line
    from core.ocr.ppocr import PPOCR
    from core.paths import DATA, user_dir
    from PySide6.QtWidgets import QApplication
    from app.options import OptionsDialog
    app = QApplication([])
    dialog = OptionsDialog()
    assert dialog.language == "zh"
    assert read_line("你好", "zh", "es")[0].candidates
    assert read_line("食べました。", "ja", "es")[0].candidates
    image = Image.open(DATA.parent / "self-test" / "horizontal-compound.png")
    text = PPOCR(script="japanese").read(image).text
    assert "日本語" in text, text
    from core.anki.japanese import furigana
    assert "<ruby>" in furigana("食べる", "たべる")
    output = {"ok": True, "ocr": text, "assets": str(DATA), "settings": str(user_dir())}
    if "--report" in sys.argv:
        Path(sys.argv[sys.argv.index("--report")+1]).write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
else:
    from app.main import main
    sys.exit(main())
