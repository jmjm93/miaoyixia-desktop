"""Small runtime English/Spanish UI catalogue."""

_language = "en"
_seen = {}
STRINGS = {
    "General": "General", "Anki · Chinese": "Anki · Chino", "Anki · Japanese": "Anki · Japonés",
    "Enable Anki export": "Activar exportación a Anki", "AnkiConnect address": "Dirección de AnkiConnect",
    "Deck": "Mazo", "Note type": "Tipo de nota", "Tags": "Etiquetas", "Audio": "Audio",
    "Recordings, then speech": "Grabaciones y, si faltan, voz sintética", "Recordings only": "Solo grabaciones",
    "Speech only": "Solo voz sintética", "Off": "Desactivado", "Speech service": "Servicio de voz",
    "Export script": "Escritura al exportar", "As read": "Como se leyó", "Simplified": "Simplificado",
    "Traditional": "Tradicional", "Speech voice": "Voz sintética", "Field name": "Nombre del campo",
    "Content": "Contenido", "Add field": "Añadir campo", "Remove field": "Eliminar campo",
    "Fields: Anki field name → content": "Campos: nombre en Anki → contenido",
    "Settings do not modify existing Anki notes or templates.": "Estos ajustes no modifican las notas ni plantillas existentes de Anki.",
    "Enter a valid AnkiConnect HTTP address.": "Introduce una dirección HTTP válida de AnkiConnect.",
    "Deck and note type cannot be empty.": "El mazo y el tipo de nota no pueden estar vacíos.",
    "Field names must be nonempty and unique.": "Los nombres de campo deben ser únicos y no estar vacíos.",
    "Add at least one field.": "Añade al menos un campo.",
    "(empty)": "(vacío)", "Word": "Palabra", "Kana reading": "Lectura en kana",
    "Word with furigana": "Palabra con furigana", "Word, tone-coloured": "Palabra con tonos coloreados",
    "Definitions": "Definiciones", "Definitions, numbered": "Definiciones numeradas",
    "First definition": "Primera definición", "Line it was read in": "Frase original",
    "Line, word emboldened": "Frase con la palabra en negrita", "Pinyin, numbered": "Pinyin numerado",
    "Pinyin, tone-coloured": "Pinyin con tonos coloreados",
    "Options": "Opciones", "User language": "Idioma del usuario",
    "Text language for new captures": "Idioma del texto para nuevas capturas",
    "Chinese · 中文": "Chino · 中文", "Japanese · 日本語": "Japonés · 日本語",
    "Save": "Guardar", "Cancel": "Cancelar", "Quit": "Salir",
    "Ready": "Listo", "Starting…": "Iniciando…", "Retry": "Reintentar",
    "Snip again": "Volver a seleccionar", "Close  (Esc)": "Cerrar  (Esc)",
    "Enable translation": "Activar traducción", "Disable translation": "Desactivar traducción",
    "Translating…": "Traduciendo…", "reading…": "leyendo…",
    "Manual region": "Región manual", "Watching a region": "Observando una región",
    "  Stop watching": "  Dejar de observar", "Stop watching": "Dejar de observar",
    "loading the dictionary and recogniser": "cargando el diccionario y el reconocimiento",
    "Snip anything, or pin a region to watch": "Captura texto o fija una región",
    "Snip text, pin a region, or open Options": "Captura texto, fija una región o abre Opciones",
    "Runs in the tray. Closing this window leaves it running.": "Permanece activo en la bandeja al cerrar esta ventana.",
    "Drag a box over any text and read it": "Selecciona un área de texto para leerla",
    "Pin an area that keeps changing -- a dialogue box -- and re-read it automatically": "Fija un área, como un cuadro de diálogo, para leer sus cambios automáticamente",
    "The full text translation will appear here": "Aquí aparecerá la traducción del texto completo",
    "nothing legible — try framing tighter, or type it above": "texto ilegible — ajusta la selección o escríbelo arriba",
    "Applies to new captures and pinned regions.\nAn existing region keeps its current language.": "Se aplica a nuevas capturas y regiones.\nLas regiones existentes conservan su idioma.",
    "Switch to manual mode": "Cambiar al modo manual", "Rescan region": "Volver a leer la región",
    "re-reading on change": "lectura automática al cambiar el texto",
    "✓ in deck": "✓ en el mazo", "✓ added": "✓ añadido", "adding…": "añadiendo…",
    "checking…": "comprobando…", "added · no audio": "añadido · sin audio",
}


def set_language(language):
    global _language
    if language not in ("en", "es"):
        raise ValueError("user language must be en or es")
    _language = language


def tr(text):
    if not isinstance(text, str):
        return text
    reverse = {v: k for k, v in STRINGS.items()}
    original = _seen.get(text, reverse.get(text, text))
    if _language == "en":
        return original
    if original in STRINGS:
        return STRINGS[original]
    replacements = {
        "Snip once": "Capturar una vez", "Watch a region": "Observar una región",
        "New captures: Chinese": "Nuevas capturas: chino", "New captures: Japanese": "Nuevas capturas: japonés",
        "Read the Chinese on your screen": "Lee el chino de tu pantalla",
        "Read the Japanese on your screen": "Lee el japonés de tu pantalla",
        "Translation ·": "Traducción ·", "Translation unavailable:": "Traducción no disponible:",
        "As read:": "Texto original:", "Rescan pinned region": "Volver a leer la región",
        "Manual mode · click to switch": "Modo manual · pulsa para cambiar",
        "Automatic mode · click to switch": "Modo automático · pulsa para cambiar",
        "Rescan with the region button or": "Vuelve a leer con el botón de la región o",
        "re-read whenever the text changes": "lectura automática al cambiar el texto",
        "whole-crop fallback": "lectura del área completa", "min score": "confianza mínima",
    }
    for source, target in replacements.items():
        original = original.replace(source, target)
    source = _seen.get(text, reverse.get(text, text))
    if original != source:
        if len(_seen) >= 512:
            _seen.clear()
        _seen[original] = source
    return original


def localize(root):
    """Refresh existing widget labels without touching recognized text or definitions."""
    from PySide6.QtWidgets import QLabel, QPushButton, QPlainTextEdit, QComboBox, QWidget
    for obj in [root, *root.findChildren(QWidget)]:
        pairs = [("toolTip", "setToolTip")]
        if isinstance(obj, (QLabel, QPushButton)) and obj.objectName() not in ("headword", "sense", "pinyin", "chip", "tab"):
            pairs.append(("text", "setText"))
        if isinstance(obj, QPlainTextEdit):
            pairs.append(("placeholderText", "setPlaceholderText"))
        for getter, setter in pairs:
            text = getattr(obj, getter)()
            key = "_original_" + getter
            old = obj.property(key)
            last = obj.property(key + "_last")
            source = old if old is not None and text == last else text
            translated = tr(source)
            obj.setProperty(key, source)
            obj.setProperty(key + "_last", translated)
            getattr(obj, setter)(translated)
        if isinstance(obj, QComboBox):
            for i in range(obj.count()):
                obj.setItemText(i, tr(obj.itemText(i)))
    root.setWindowTitle(tr(root.windowTitle()))
