"""The Anki export, exercised without Anki.

A port of the extension's test/anki.test.mjs, which is most of the value of porting the feature:
the behaviours asserted here are the ones that were got wrong once already -- duplicate scoping,
field reconciliation, and the two places where dictionary text reaches an HTML field.

Everything talks to AnkiClient through an injected transport, so nothing here opens a socket.
The one exception is deliberate and says so.
"""

import dataclasses
import json
from dataclasses import replace

import pytest

from core import config as anki_config
from core.anki.client import (
    AnkiClient,
    AnkiUnreachableError,
    ensure_target,
    note_options,
    reconcile_mapping,
)
from core.anki.export import add_card, browse_card, inspect_cards, search_queries
from core.anki.fields import (
    build_fields,
    coloured_hanzi,
    coloured_pinyin,
    escape_html,
    primary_field,
    sentence_with_word_bold,
)
from core.lang.dict_store import Entry
from core.reading import apply_script, build_card

DEFAULT_MAPPING = anki_config.DEFAULTS["anki"]["fields"]


@pytest.fixture(autouse=True)
def no_external_audio(monkeypatch):
    # Audio fetching and media export have their own injected-source tests.
    monkeypatch.setattr("core.anki.export.resolve", lambda *args: None)


def _card(headword="居民", simplified="居民", traditional="居民", pinyin="ju1 min2",
          gloss="resident/inhabitant", sentence=""):
    return build_card(headword, Entry(simplified, traditional, pinyin, gloss), sentence)


def _client(responses):
    """A client whose transport answers from a dict, and records what it was asked."""
    calls = []

    def transport(action, params):
        calls.append((action, params))
        value = responses[action]
        return value(params) if callable(value) else value

    client = AnkiClient(transport=transport)
    return client, calls


# --- field rendering -------------------------------------------------------------------


def test_dictionary_text_is_escaped_since_anki_fields_are_html():
    # No slash in the gloss: CC-CEDICT separates senses with one, so a slash here would be
    # testing the dictionary parser rather than the escaping.
    card = _card(gloss='a <b>bold<b> & brash "one"')
    assert build_fields({"English": "senses"}, card)["English"] == (
        "a &lt;b&gt;bold&lt;b&gt; &amp; brash &quot;one&quot;"
    )
    assert escape_html("<&>") == "&lt;&amp;&gt;"


def test_tone_colours_the_word_one_span_per_character():
    assert coloured_hanzi(_card(), {}) == (
        '<span class="tone1">居</span><span class="tone2">民</span>'
    )


def test_falls_back_to_plain_text_when_characters_and_syllables_do_not_align():
    """卡拉OK and AA制 have more characters than syllables.

    Confidently wrong colours are worse than none: the colour *is* the tone information on a
    card, so a misaligned span teaches the wrong tone rather than merely looking odd.
    """
    card = replace(_card(), headword="卡拉OK")
    assert coloured_hanzi(card, {}) == "卡拉OK"


def test_tone_colours_pinyin_per_syllable_and_keeps_the_toneless_reading_in_a_comment():
    rendered = coloured_pinyin(_card(), {})
    assert rendered == (
        '<span class="tone1">jū</span> <span class="tone2">mín</span> <!-- ju min -->'
    )


def test_tone_zero_falls_back_to_tone5_the_only_class_templates_define():
    # A middot or a Latin abbreviation parses as a syllable with no tone at all.
    card = _card(headword="·", simplified="·", traditional="·", pinyin="·")
    assert 'class="tone5"' in coloured_hanzi(card, {})


def test_emboldens_the_word_inside_its_sentence():
    card = _card(sentence="倖存的居民皆已收容完畢")
    assert sentence_with_word_bold(card, {}) == "倖存的<b>居民</b>皆已收容完畢"


def test_escapes_the_sentence_before_emboldening_so_recognised_text_cannot_inject_markup():
    """OCR output is not trusted input. It is whatever was on screen, which could be anything."""
    card = _card(sentence="<script>x</script>居民")
    assert sentence_with_word_bold(card, {}) == "&lt;script&gt;x&lt;/script&gt;<b>居民</b>"


def test_the_sentence_is_bolded_on_the_form_that_was_read_not_the_exported_one():
    """The desktop half of the extension's `hovered` rule.

    Exporting to simplified rewrites the headword to 个, but the line on screen says 個 -- so
    matching on the headword would find nothing and silently drop the emboldening.
    """
    card = _card(headword="個", simplified="个", traditional="個", pinyin="ge4",
                 gloss="individual", sentence="這個人")
    written = apply_script(card, "simplified")

    assert written.headword == "个"
    assert written.as_read == "個"
    assert sentence_with_word_bold(written, {}) == "這<b>個</b>人"


def test_a_script_preference_that_would_mangle_the_word_is_ignored():
    """Rewriting only holds when the two scripts agree character for character.

    They usually do, but 麽/么 style entries where the forms differ in length would otherwise
    desynchronise the headword from its syllables and take the tone colouring with them.
    """
    card = replace(_card(), simplified="居")
    assert apply_script(card, "simplified").headword == "居民"


# --- the token table -------------------------------------------------------------------


def test_every_token_id_is_unique_and_renders_a_string_for_a_real_card():
    from core.anki.fields import TOKENS

    ids = [token.id for token in TOKENS]
    assert len(ids) == len(set(ids))

    card = _card(sentence="倖存的居民皆已收容完畢")
    for token in TOKENS:
        assert isinstance(token.render(card, {}), str), token.id


def test_the_audio_token_is_empty_unless_a_media_file_was_actually_stored():
    """An empty field beats a dangling [sound:] tag."""
    card = _card()
    assert build_fields({"Sound": "audio"}, card)["Sound"] == ""
    assert build_fields({"Sound": "audio"}, card, {"audioFilename": "x.mp3"})["Sound"] == (
        "[sound:x.mp3]"
    )


def test_builds_fields_from_the_shipped_default_mapping():
    fields = build_fields(DEFAULT_MAPPING, _card())
    assert fields["Hanzi"] == "居民"
    assert fields["Color"] == '<span class="tone1">居</span><span class="tone2">民</span>'
    assert fields["Pinyin"].startswith('<span class="tone1">jū</span>')
    assert fields["English"] == "resident<br>inhabitant"
    assert fields["Sound"] == ""


def test_field_names_are_arbitrary_so_a_differently_named_note_type_works_unchanged():
    fields = build_fields({"Expression": "headword", "Reading": "pinyin"}, _card())
    assert fields == {"Expression": "居民", "Reading": "jū mín"}


def test_an_unknown_token_yields_an_empty_field_rather_than_losing_the_note():
    """Covers a config lifted from the extension, which has `source` tokens this side lacks."""
    fields = build_fields({"Hanzi": "headword", "Where": "sourceUrl"}, _card())
    assert fields == {"Hanzi": "居民", "Where": ""}


def test_the_front_of_an_auto_created_note_type_is_whichever_field_holds_the_word():
    assert primary_field(DEFAULT_MAPPING) == "Hanzi"
    assert primary_field({"Meaning": "senses", "Word": "colourHanzi"}) == "Word"
    # Nothing holds the word: the first field is still a better front than an empty one.
    assert primary_field({"Meaning": "senses", "Reading": "pinyin"}) == "Meaning"


# --- talking to Anki -------------------------------------------------------------------


def test_classifies_a_duplicate_distinctly_from_other_refusals():
    """The button says "already in deck" for one and shows the reason for the other."""
    client, _ = _client(
        {
            "canAddNotesWithErrorDetail": [
                {"canAdd": True},
                {"canAdd": False, "error": "cannot create note because it is a duplicate"},
                {"canAdd": False, "error": "cannot create note because it is empty"},
            ]
        }
    )
    states = client.inspect([{}, {}, {}])

    assert [s["canAdd"] for s in states] == [True, False, False]
    assert [s["duplicate"] for s in states] == [False, True, False]
    assert "empty" in states[2]["error"]


def test_scopes_the_duplicate_check_to_the_target_deck_not_the_whole_collection():
    """AnkiConnect's default ignores the deck, so a word mined once could never be mined again.

    A mining deck is a working set; the same word belonging to two of them is normal.
    """
    options = note_options("Mandarin::Chinese Mining")
    assert options["duplicateScope"] == "deck"
    assert options["duplicateScopeOptions"]["deckName"] == "Mandarin::Chinese Mining"
    assert options["duplicateScopeOptions"]["checkChildren"] is True
    assert options["duplicateScopeOptions"]["checkAllModels"] is False


def test_the_inspect_and_add_paths_ask_anki_the_same_question():
    """If they disagreed the button would offer a note that the add then refuses."""
    config = anki_config.load(_missing_path()).anki
    card = _card()
    responses = {
        "deckNames": [config.deck],
        "modelNames": [config.model],
        "modelFieldNames": list(DEFAULT_MAPPING),
        "canAddNotesWithErrorDetail": [{"canAdd": True}],
        "addNote": 99,
    }
    client, calls = _client(responses)

    inspect_cards(client, config, [card])
    inspected = dict(calls)["canAddNotesWithErrorDetail"]["notes"][0]

    client, calls = _client(responses)
    add_card(client, config, card)
    added = dict(calls)["addNote"]["note"]

    assert inspected["fields"] == added["fields"]
    assert inspected["options"] == added["options"]


def test_inspect_reports_addable_and_creates_nothing_when_the_target_is_missing():
    """Showing a word must never mutate the collection; creation belongs to the click."""
    config = anki_config.load(_missing_path()).anki
    client, calls = _client({"deckNames": [], "modelNames": []})

    result = inspect_cards(client, config, [_card(), _card()])

    assert result["ready"] is False
    assert [s["canAdd"] for s in result["states"]] == [True, True]
    assert [action for action, _ in calls] == ["deckNames", "modelNames"]


def test_creates_only_what_is_missing_and_says_what_it_made():
    client, calls = _client(
        {"deckNames": ["Mandarin"], "modelNames": ["Basic"], "createDeck": 1, "createModel": {}}
    )
    created = ensure_target(client, "Mandarin", "Chinese (Basic)", DEFAULT_MAPPING)

    assert created == ["note type Chinese (Basic)"]
    assert "createDeck" not in [action for action, _ in calls]

    client, _ = _client({"deckNames": ["Mandarin"], "modelNames": ["Chinese (Basic)"]})
    assert ensure_target(client, "Mandarin", "Chinese (Basic)", DEFAULT_MAPPING) == []


def test_an_auto_created_note_type_carries_the_tone_css_its_fields_need():
    """Without .tone1-.tone5 the tone-coloured fields render as plain text on the card."""
    client, calls = _client({"createModel": {}})
    client.create_model("Chinese (Basic)", DEFAULT_MAPPING)

    params = dict(calls)["createModel"]
    assert params["inOrderFields"] == list(DEFAULT_MAPPING)
    assert "{{Hanzi}}" in params["cardTemplates"][0]["Front"]
    for tone in range(1, 6):
        assert f".tone{tone}" in params["css"]


def test_an_unreachable_anki_surfaces_as_a_typed_error_not_a_silent_failure():
    """The one test that opens a socket -- to a closed loopback port, so it fails at once.

    Typed because the window treats it differently from a refusal: there is nothing to retry
    against, so every button goes quiet rather than showing a reason per word.
    """
    client = AnkiClient(origin="http://127.0.0.1:1", timeout=1.0)
    with pytest.raises(AnkiUnreachableError):
        client.version()


def test_reconciling_drops_fields_the_note_type_lacks_and_adds_ones_it_has():
    """Sending a field the note type does not have makes AnkiConnect reject the whole note."""
    reconciled = reconcile_mapping({"Hanzi": "headword", "Gone": "pinyin"}, ["Hanzi", "Extra"])
    assert reconciled == {"Hanzi": "headword", "Extra": "none"}


def test_an_added_note_carries_the_configured_tags():
    config = anki_config.load(_missing_path()).anki
    client, calls = _client(
        {
            "deckNames": [config.deck],
            "modelNames": [config.model],
            "modelFieldNames": list(DEFAULT_MAPPING),
            "addNote": 77,
        }
    )
    result = add_card(client, config, _card())

    assert result["noteId"] == 77
    assert dict(calls)["addNote"]["note"]["tags"] == ["miao-yixia"]


def test_a_deck_name_keeps_its_separators_when_searched_for():
    """:: is Anki's deck separator, not a colon to be escaped.

    Escaped, "Mandarin::Chinese Mining" becomes a search for a top-level deck whose name
    contains two literal colons, which matches nothing -- so the browser would open empty for
    every word in the default deck, which is to say all of them.
    """
    from core.anki.export import escape_search

    assert escape_search("Mandarin::Chinese Mining", colons=False) == "Mandarin::Chinese Mining"
    # In an ordinary term the same colon would be read as a field separator.
    assert escape_search("a:b") == r"a\:b"


def test_recognised_text_cannot_break_out_of_a_search():
    """OCR of a stylised panel really does produce quotes and asterisks."""
    from core.anki.export import escape_search

    assert escape_search('美工"们"') == '美工\\"们\\"'
    assert escape_search("a*b_c") == r"a\*b\_c"


def test_browsing_settles_on_a_query_that_matches_before_opening_anki():
    """One window, on something -- not a flicker through queries that match nothing."""
    config = anki_config.load(_missing_path()).anki
    # Only the deck-wide search finds it, which is the case that matters: a first field bound to
    # colourHanzi holds <span> tags, so no search for the bare word can match it.
    hits = {'"deck:Mandarin::Chinese Mining" "居民"': [42]}
    client, calls = _client(
        {
            "modelFieldNames": ["Hanzi", "Color"],
            "findNotes": lambda p: hits.get(p["query"], []),
            "guiBrowse": lambda p: hits.get(p["query"], []),
        }
    )
    result = browse_card(client, config, _card())

    assert result["found"] == [42]
    browsed = [p["query"] for action, p in calls if action == "guiBrowse"]
    assert browsed == ['"deck:Mandarin::Chinese Mining" "居民"'], "the browser opened more than once"


def test_browsing_a_word_no_search_can_find_still_opens_the_browser():
    """Anki said duplicate, so the note exists and the search is what is wrong.

    An open browser makes that visible and leaves the user a query to edit; doing nothing at all
    looks like a broken button.
    """
    config = anki_config.load(_missing_path()).anki
    client, calls = _client(
        {"modelFieldNames": ["Hanzi"], "findNotes": [], "guiBrowse": []}
    )
    result = browse_card(client, config, _card())

    assert result["query"]
    assert "guiBrowse" in [action for action, _ in calls]


def test_the_browse_query_uses_the_exported_script_not_the_form_on_screen():
    """Export rewrites 個 to 个, so that is what is in the deck to be found."""
    config = dataclasses.replace(anki_config.load(_missing_path()).anki, script="simplified")
    card = _card(headword="個", simplified="个", traditional="個", pinyin="ge4", gloss="individual")
    client, _ = _client({"modelFieldNames": ["Hanzi"]})

    assert all("个" in q for q in search_queries(client, config, card))
    assert not any("個" in q for q in search_queries(client, config, card))


# --- the config file -------------------------------------------------------------------


def _missing_path():
    return anki_config.CONFIG_PATH.parent / "does-not-exist.json"


def test_the_defaults_are_the_extension_s(tmp_path):
    config = anki_config.load(tmp_path / "none.json").anki
    assert config.enabled is False
    assert config.deck == "Mandarin::Chinese Mining"
    assert config.model == "Chinese (Basic)"
    assert config.tags == "miao-yixia"


def test_a_config_only_has_to_say_what_it_changes(tmp_path):
    """Nobody should have to restate the field mapping to point at a different deck."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"anki": {"enabled": True, "deck": "Reading"}}), encoding="utf-8")

    config = anki_config.load(path).anki
    assert (config.enabled, config.deck) == (True, "Reading")
    assert config.model == "Chinese (Basic)"
    assert config.fields == DEFAULT_MAPPING


def test_naming_the_field_mapping_replaces_it_rather_than_merging_into_it(tmp_path):
    """A mapping is one object, not a bag of keys.

    Merged, a default field the user deliberately removed would come back -- and AnkiConnect
    rejects the entire note over one field the note type does not have, so the failure would land
    on the add, far from the config that caused it.
    """
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"anki": {"fields": {"Expression": "headword"}}}), encoding="utf-8"
    )
    assert anki_config.load(path).anki.fields == {"Expression": "headword"}


def test_a_malformed_config_falls_back_to_the_defaults_and_says_so(tmp_path):
    """Starting is not negotiable. A typo in a settings file must not cost the whole app."""
    path = tmp_path / "config.json"
    path.write_text("{ not json", encoding="utf-8")

    config = anki_config.load(path)
    assert config.error
    assert config.anki.deck == "Mandarin::Chinese Mining"


def test_the_default_config_is_written_once_and_never_over_an_edited_one(tmp_path):
    path = tmp_path / "config.json"

    assert anki_config.write_defaults(path) is True
    path.write_text(json.dumps({"anki": {"deck": "Mine"}}), encoding="utf-8")

    assert anki_config.write_defaults(path) is False
    assert anki_config.load(path).anki.deck == "Mine"


def test_the_written_default_config_is_the_one_the_app_would_have_used_anyway(tmp_path):
    """The file has to be a starting point, not a second opinion."""
    path = tmp_path / "config.json"
    anki_config.write_defaults(path)
    assert anki_config.load(path) == replace(
        anki_config.load(tmp_path / "absent.json"), path=path
    )
