"""Anki, off the GUI thread.

The same shape as worker.py and for the same reason, but a different hazard. Recognition is slow
and bounded; AnkiConnect is fast when Anki is running and *unbounded* when it is not quite --
mid-sync, mid-dialog, or listening on a port something else has taken. A 5s timeout on the GUI
thread is a five-second frozen window, so it gets a thread of its own.

Its own thread rather than the recogniser's, too: a stalled add must not hold up the next snip,
which is the one thing the user can always fall back on.

Every reply carries the `ticket` its request was made with. Words are clicked through faster than
a round trip completes, so a result that arrives for a word no longer on screen has to be
discarded rather than applied to whatever is showing now -- and only the caller knows which is
which. See ResultWindow._anki_ticket.
"""

from PySide6.QtCore import QObject, QThread, Signal, Slot

from core.anki.client import AnkiClient, AnkiError, AnkiUnreachableError
from core.config import AnkiConfig
from core.anki.export import add_card, browse_card, inspect_cards


class Anki(QObject):
    """Lives on the worker thread. Talk to it only through signals and queued slots."""

    #: ticket, {"ready": bool, "states": [...]}
    inspected = Signal(int, object)
    #: ticket, index of the card within the candidate, {"noteId", "created", "deck"}
    added = Signal(int, int, object)
    #: ticket, index, message, whether Anki refused it as a duplicate. Shared by the add and
    #: browse paths: both end on the same button, and the button has one way to say "that did
    #: not work".
    failed = Signal(int, int, str, bool)
    #: Anki could not be reached at all. Distinct from a refusal: there is nothing to retry
    #: against and every button should simply go quiet.
    unreachable = Signal(int, str)

    def __init__(self):
        super().__init__()
        self._client: AnkiClient | None = None
        self._origin = ""

    def _for(self, config: AnkiConfig) -> AnkiClient:
        # One client, rebuilt only when the configured origin changes. urllib opens a connection
        # per call regardless, so this is not pooling -- it is just somewhere for the origin to
        # live that is not re-derived on every request.
        if self._client is None or self._origin != config.origin:
            self._client = AnkiClient(origin=config.origin)
            self._origin = config.origin
        return self._client

    @Slot(int, object, object)
    def inspect(self, ticket: int, config: AnkiConfig, cards: list) -> None:
        try:
            result = inspect_cards(self._for(config), config, cards)
        except AnkiUnreachableError as exc:
            self.unreachable.emit(ticket, str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - a greyed-out button is not worth a crash
            self.unreachable.emit(ticket, f"Anki: {exc}")
            return
        self.inspected.emit(ticket, result)

    @Slot(int, int, object, object)
    def add(self, ticket: int, index: int, config: AnkiConfig, card) -> None:
        try:
            result = add_card(self._for(config), config, card)
        except AnkiUnreachableError as exc:
            self.unreachable.emit(ticket, str(exc))
            return
        except AnkiError as exc:
            # A duplicate is the expected way for an add to fail -- the word is already studied --
            # so the window says so rather than reporting an error.
            self.failed.emit(ticket, index, str(exc), exc.duplicate)
            return
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(ticket, index, str(exc), False)
            return
        self.added.emit(ticket, index, result)

    @Slot(int, int, object, object)
    def browse(self, ticket: int, index: int, config: AnkiConfig, card) -> None:
        """Open Anki's browser on the note this card is a duplicate of.

        No success signal: Anki's own window appearing is the feedback, and there is nothing
        about the button that should change -- the word is still in the deck.
        """
        try:
            browse_card(self._for(config), config, card)
        except AnkiUnreachableError as exc:
            self.unreachable.emit(ticket, str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(ticket, index, str(exc), False)


class AnkiThread(QObject):
    """Owns the worker thread and the Anki client on it.

    Requests go out as *signals*, never as method calls -- see EngineThread for why that
    distinction is load-bearing and fails silently when got wrong.
    """

    request_inspect = Signal(int, object, object)
    request_add = Signal(int, int, object, object)
    request_browse = Signal(int, int, object, object)

    def __init__(self):
        super().__init__()
        self.thread = QThread()
        self.thread.setObjectName("anki")
        self.anki = Anki()
        self.anki.moveToThread(self.thread)

        self.request_inspect.connect(self.anki.inspect)
        self.request_add.connect(self.anki.add)
        self.request_browse.connect(self.anki.browse)

        self.thread.start()

    def inspect(self, ticket: int, config: AnkiConfig, cards: list) -> None:
        self.request_inspect.emit(ticket, config, list(cards))

    def add(self, ticket: int, index: int, config: AnkiConfig, card) -> None:
        self.request_add.emit(ticket, index, config, card)

    def browse(self, ticket: int, index: int, config: AnkiConfig, card) -> None:
        self.request_browse.emit(ticket, index, config, card)

    def stop(self) -> None:
        self.thread.quit()
        # Bounded: a request waiting out its timeout must not stop the app from exiting.
        # Audio downloads are bounded but can outlast a single AnkiConnect timeout.
        # Keep the worker alive until it returns, rather than destroying a running QThread.
        self.thread.wait()
