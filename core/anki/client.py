"""AnkiConnect client. A port of the extension's lib/anki.js.

AnkiConnect answers with HTTP 200 and {result, error} even for failures, so `error` has to be
checked rather than the status code.

urllib rather than a dependency: these are small JSON POSTs to loopback, and the one thing that
actually matters -- a timeout, so a wedged Anki cannot hang the caller forever -- urlopen gives
directly. The extension's fetch needed a host permission to cross origins; a desktop process has
no such constraint, which removes the only reason that file had to live in a service worker.
"""

import json
import urllib.error
import urllib.request

from core.anki.fields import primary_field

ANKI_ORIGIN = "http://127.0.0.1:8765"
API_VERSION = 6
#: Loopback to a program on the same machine. Long enough for Anki to be busy, short enough that
#: a click cannot appear to hang.
TIMEOUT = 5.0

#: AnkiConnect's wording when Anki itself refuses a note for being a duplicate.
DUPLICATE_MARKER = "duplicate"


class AnkiUnreachableError(Exception):
    """Anki is closed, AnkiConnect is not installed, or something is in the way."""


class AnkiError(Exception):
    """AnkiConnect was reached and said no."""

    @property
    def duplicate(self) -> bool:
        return DUPLICATE_MARKER in str(self).lower()


def note_options(deck_name: str) -> dict:
    """The `options` every note is sent with, inspected or added.

    Duplicates are scoped to the target deck. AnkiConnect's default is the whole collection for
    the note type, which ignores the deck entirely -- so a word already mined into one deck came
    back as a duplicate in a brand new one, with no way to add it. A mining deck is a working set,
    and the same word belonging to two of them is the normal case, not a mistake.

    `checkChildren` because the shipped default deck has subdecks ("Mandarin::Chinese Mining"),
    and a word in a child deck is genuinely already in that tree. `checkAllModels` stays off so
    the check follows Anki's own rule of comparing within one note type.

    Used by both the inspect and the add path on purpose: if they disagreed, the button would
    offer a note that the add then refuses.
    """
    return {
        "allowDuplicate": False,
        "duplicateScope": "deck",
        "duplicateScopeOptions": {
            "deckName": deck_name,
            "checkChildren": True,
            "checkAllModels": False,
        },
    }


class AnkiClient:
    """Every call blocks. Keep it off the GUI thread -- see app/anki.py."""

    def __init__(self, origin: str = ANKI_ORIGIN, timeout: float = TIMEOUT, transport=None):
        self.origin = origin
        self.timeout = timeout
        #: Injected by the tests, which have no Anki to talk to.
        self._transport = transport

    def invoke(self, action: str, **params):
        if self._transport is not None:
            return self._transport(action, params)

        payload = json.dumps({"action": action, "version": API_VERSION, "params": params})
        request = urllib.request.Request(
            self.origin,
            data=payload.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.load(response)
        except urllib.error.HTTPError as exc:
            raise AnkiError(f"AnkiConnect returned {exc.code} for {action}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise AnkiUnreachableError(f"Cannot reach Anki at {self.origin}") from exc

        if body.get("error"):
            raise AnkiError(body["error"])
        return body.get("result")

    # --- reading the collection --------------------------------------------------------

    def version(self) -> int:
        return self.invoke("version")

    def deck_names(self) -> list[str]:
        return self.invoke("deckNames")

    def model_names(self) -> list[str]:
        return self.invoke("modelNames")

    def model_field_names(self, model_name: str) -> list[str]:
        return self.invoke("modelFieldNames", modelName=model_name)

    def find_notes(self, query: str) -> list[int]:
        return self.invoke("findNotes", query=query)

    def inspect(self, notes: list[dict]) -> list[dict]:
        """Ask Anki whether each note could be added, and say why not.

        This is the authoritative duplicate check: it uses Anki's own logic on the note type's
        first field, so a greyed-out button matches exactly what Anki would refuse -- provided
        both sides ask the same question, which is what note_options() is for.
        """
        states = []
        for result in self.invoke("canAddNotesWithErrorDetail", notes=notes):
            can_add = bool(result.get("canAdd"))
            error = "" if can_add else (result.get("error") or "unknown")
            states.append(
                {
                    "canAdd": can_add,
                    "duplicate": not can_add and DUPLICATE_MARKER in error.lower(),
                    "error": error,
                }
            )
        return states

    # --- writing to it ------------------------------------------------------------------

    def add_note(self, note: dict) -> int:
        return self.invoke("addNote", note=note)

    def store_media(self, filename: str, base64_data: str) -> str:
        """Returns the filename Anki actually stored it under."""
        return self.invoke("storeMediaFile", filename=filename, data=base64_data)

    def create_deck(self, deck: str) -> int:
        return self.invoke("createDeck", deck=deck)

    def gui_browse(self, query: str) -> list[int]:
        """Open Anki's Browse window on `query`, and return what it selected.

        Counts as writing only in that it moves Anki's own windows about; it changes no notes.
        """
        return self.invoke("guiBrowse", query=query)

    def create_model(self, model_name: str, mapping: dict[str, str]):
        """Create a note type with the given field names, a card template, and the tone CSS the
        coloured fields rely on.

        Generated from the mapping rather than written out, so it works whatever the user named
        their fields.
        """
        fields = list(mapping)
        front = primary_field(mapping)
        rest = [f for f in fields if f != front and mapping[f] != "none"]
        back = ["{{FrontSide}}", "<hr id=answer>"]
        back += ['<div class="zh-%s">{{%s}}</div>' % (_slug(f), f) for f in rest]

        return self.invoke(
            "createModel",
            modelName=model_name,
            inOrderFields=fields,
            isCloze=False,
            css=MODEL_CSS,
            cardTemplates=[
                {
                    "Name": "Recognition",
                    "Front": '<div class="zh-word">{{%s}}</div>' % front,
                    "Back": "\n".join(back),
                }
            ],
        )


def _slug(name: str) -> str:
    out = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-") or "field"


#: Styling for an auto-created note type. The .tone1-.tone5 rules are the important part --
#: without them the tone-coloured fields render as plain text. These are the conventional
#: colours, matching what existing Chinese note types use.
MODEL_CSS = """.card {
  font-family: system-ui, "Microsoft YaHei", "PingFang SC", sans-serif;
  font-size: 20px;
  text-align: center;
  color: #1a1a1a;
  background-color: #ffffff;
  word-wrap: break-word;
}

.zh-word { font-size: 64px; margin: 12px 0; }
.zh-pinyin, .zh-reading { font-size: 28px; }
.zh-english, .zh-meaning { font-size: 20px; margin-top: 10px; }

.tone1 { color: #c0392b; }
.tone2 { color: #b7791f; }
.tone3 { color: #2f7d32; }
.tone4 { color: #2b5fd9; }
.tone5 { color: #6b7280; }

@media (prefers-color-scheme: dark) {
  .card { color: #e8eaed; background-color: #1f2227; }
  .tone1 { color: #f2777a; }
  .tone2 { color: #e0b060; }
  .tone3 { color: #8fc98f; }
  .tone4 { color: #7aa2f7; }
  .tone5 { color: #9aa0a6; }
}
"""


def ensure_target(client: AnkiClient, deck: str, model: str, fields: dict[str, str]) -> list[str]:
    """Make sure the configured deck and note type exist, creating either if it doesn't.

    Deliberately called on the first *add*, not while merely inspecting: showing a word should
    never mutate the collection. Returns what had to be created, so the window can say so.
    """
    created = []

    if deck not in client.deck_names():
        client.create_deck(deck)
        created.append(f"deck {deck}")

    if model not in client.model_names():
        client.create_model(model, fields)
        created.append(f"note type {model}")

    return created


def reconcile_mapping(mapping: dict[str, str], actual_fields: list[str]) -> dict[str, str]:
    """Field names the collection actually has, reconciled with the configured mapping.

    Fields the note type doesn't have are dropped -- sending them makes AnkiConnect reject the
    whole note -- and fields it has but the mapping doesn't mention are added as empty.
    """
    return {field: mapping.get(field, "none") for field in actual_fields}
