"""Read-only live Yomi validation and Japanese audio smoke checks. Does not add notes."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.config import load
from core.anki.client import AnkiClient, reconcile_mapping
from core.anki.export import _note
from core.anki.japanese import resolve
from core.reading import read_line

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
config = load().anki_japanese
client = AnkiClient(config.origin)
fields = client.model_field_names(config.model)
tokens = read_line("食べました。", "ja")
card = tokens[0].candidates[tokens[0].default].cards[0]
note = _note(config, reconcile_mapping(config.fields, fields), card)
print(json.dumps(note, ensure_ascii=False, indent=2))
print("Anki validation:", client.inspect([note]))
decks = client.deck_names()
if config.deck not in decks and decks:
    print("Field validation in an existing deck:", client.inspect([{**note, "deckName": decks[0],
        "options": {"allowDuplicate": True}}]))
directory = Path(__file__).resolve().parents[1] / ".pytest_cache"
for mode in ("recording", "voice"):
    try:
        audio = resolve(card.headword, card.reading, mode, config.tts_service, config.tts_voice)
        (directory / f"japanese-{mode}.mp3").write_bytes(audio.data)
        print(mode, audio.source, len(audio.data), "bytes")
    except Exception as exc:
        print(mode, "unavailable:", exc)
