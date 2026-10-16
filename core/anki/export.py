"""The two operations the window actually asks for, ported from the extension's service worker.

Kept apart from client.py for the same reason `core/` is kept apart from `app/`: this is the
policy -- which deck, which script, which fields, what happens when the target is missing --
while the client is only the wire. Both halves are exercised without Anki running, by handing
AnkiClient a transport.
"""

import base64
import hashlib
import logging

from core.anki.audio import resolve
from core.anki.client import AnkiClient, ensure_target, note_options, reconcile_mapping
from core.config import AnkiConfig
from core.anki.fields import build_fields
from core.reading import Card, apply_script


def _note(config: AnkiConfig, mapping: dict[str, str], card: Card, extras: dict | None = None) -> dict:
    return {
        "deckName": config.deck,
        "modelName": config.model,
        "fields": build_fields(mapping, apply_script(card, config.script), extras),
        "options": note_options(config.deck),
    }


def inspect_cards(client: AnkiClient, config: AnkiConfig, cards) -> dict:
    """Can these words be added? Used to grey out the button for words already in the collection.

    Read-only on purpose: this runs whenever a word is shown, so it must never create a deck or a
    note type. If the target doesn't exist yet the words are reported as addable and creation
    happens on the click -- which is also the honest answer, since a word cannot already be in a
    deck that does not exist.
    """
    decks = client.deck_names()
    models = client.model_names()
    if config.deck not in decks or config.model not in models:
        return {
            "ready": False,
            "states": [{"canAdd": True, "duplicate": False, "error": ""} for _ in cards],
        }

    mapping = reconcile_mapping(config.fields, client.model_field_names(config.model))
    # Normalised the same way the add path will, or duplicate detection would compare a form that
    # is never written -- reporting 個 as addable when the deck already holds 个.
    notes = [_note(config, mapping, card) for card in cards]
    return {"ready": True, "states": client.inspect(notes)}


#: Wildcards and quoting, special inside a search term however it is quoted. Anything out of the
#: recogniser has to be escaped before it can be searched for -- OCR of a stylised panel really
#: does produce quotes and asterisks; the line this was first tried on was 美工"们"版证人工代证表.
_ALWAYS_SPECIAL = '\\"*_'


def escape_search(text: str, colons: bool = True) -> str:
    """Escape a value for use inside a quoted Anki search term.

    `colons=False` for a deck name, and that exception is the whole subtlety here: `::` is Anki's
    deck separator, so escaping it turns "Mandarin::Chinese Mining" into a search for a top-level
    deck with two literal colons in its name, which matches nothing. In an ordinary term a colon
    would instead be read as a field separator, so there it does need escaping.
    """
    special = _ALWAYS_SPECIAL + (":" if colons else "")
    return "".join("\\" + c if c in special else c for c in text)


def search_queries(client: AnkiClient, config: AnkiConfig, card: Card) -> list[str]:
    """Ways to find the note this card would have made, best first.

    Three rather than one because the first field is not reliably plain text. Anki compares
    duplicates on the note type's *first* field, whatever it is -- and if the mapping binds that
    field to `colourHanzi`, what is stored is a run of <span> tags that no search for 美工 will
    match. So: the exact field, then the word anywhere in the deck, then the word anywhere at all.
    """
    word = escape_search(apply_script(card, config.script).headword)
    deck = escape_search(config.deck, colons=False)

    queries = []
    fields = client.model_field_names(config.model)
    if fields:
        queries.append(f'"deck:{deck}" "{escape_search(fields[0])}:{word}"')
    queries.append(f'"deck:{deck}" "{word}"')
    queries.append(f'"{word}"')
    return queries


def browse_card(client: AnkiClient, config: AnkiConfig, card: Card) -> dict:
    """Show the existing note in Anki's browser.

    What the add button does once the word is already in the deck: there is nothing to add, and
    "already there" is far more useful as a way to go and look at it than as a dead end.

    The query is settled with findNotes before the browser is opened, so the window appears once,
    on something -- rather than flickering through queries that match nothing.
    """
    queries = search_queries(client, config, card)
    for query in queries:
        if client.find_notes(query):
            return {"query": query, "found": client.gui_browse(query)}

    # Nothing matched, which is worth showing rather than swallowing: Anki said duplicate, so the
    # note exists and the search is what is wrong. An open browser makes that visible and lets
    # the user edit the query themselves.
    return {"query": queries[-1], "found": client.gui_browse(queries[-1])}


def add_card(client: AnkiClient, config: AnkiConfig, card: Card) -> dict:
    """Add one note, creating the deck and note type first if they're missing."""
    created = ensure_target(client, config.deck, config.model, config.fields)

    mapping = reconcile_mapping(config.fields, client.model_field_names(config.model))
    extras = {}
    audio_source, audio_error = "", ""
    if "audio" in mapping.values() and config.audio != "off":
        written = apply_script(card, config.script)
        try:
            if written.language == "ja":
                from core.anki.japanese import resolve as resolve_japanese
                audio = resolve_japanese(written.headword, written.reading, config.audio,
                                         config.tts_service, config.tts_voice)
            else:
                audio = resolve(written.headword, written.simplified, written.traditional,
                                written.pinyin, config.audio, config.tts_service)
        except (OSError, ValueError) as exc:
            audio_error = str(exc)
            logging.getLogger(__name__).warning("Adding %s without audio: %s", written.headword, exc)
        else:
            if audio:
                filename = "miaoyixia_" + hashlib.sha256(audio.data).hexdigest()[:24] + audio.extension
                extras["audioFilename"] = client.store_media(filename, base64.b64encode(audio.data).decode("ascii"))
                if not extras["audioFilename"]:
                    raise ValueError("Anki did not return a stored audio filename")
                audio_source = audio.source
    note = _note(config, mapping, card, extras)
    note["tags"] = config.tag_list

    return {
        "noteId": client.add_note(note),
        "created": created,
        "deck": config.deck,
        "audio": bool(extras.get("audioFilename")),
        "audioSource": audio_source,
        "audioError": audio_error,
    }
