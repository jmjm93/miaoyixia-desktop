"""One explicitly selected language for the lifetime of a session."""
LANGUAGES = {"zh": "Chinese", "ja": "Japanese"}


def validate(language: str) -> str:
    if language not in LANGUAGES:
        raise ValueError("language must be zh or ja")
    return language


def ocr_script(language: str) -> str:
    return "japanese" if validate(language) == "ja" else "simplified"


def warm(language: str) -> None:
    if validate(language) == "ja":
        from core.lang.japanese import reader
        reader()
    else:
        from core.lang.dict_store import dictionary
        dictionary()
