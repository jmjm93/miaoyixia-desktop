# Third-party components

The project's original source code is released under the MIT License (see `LICENSE`).
This does not replace the licenses of third-party components or dictionary data.

Distributed builds include dependency licence texts and a version inventory in
`_internal/third-party-licenses`. Those licences apply to their respective components.

- Chinese dictionary: CC-CEDICT, CC BY-SA 4.0. https://cc-cedict.org/
- Spanish Chinese definitions: jmjm93/cedict-translations, derived from CC-CEDICT.
  https://github.com/jmjm93/cedict-translations — see `data/spanish/LICENSE-CEDICT`.
- Japanese dictionary: JMdict, copyright EDRDG, CC BY-SA 4.0.
  https://www.edrdg.org/edrdg/licence.html — full licence in `data/japanese/licence.html`.
  SQLite indexes are generated from jmdict-simplified releases; Spanish uses English fallback.
- Japanese morphology: Fugashi and UniDic Lite. Dictionary licences are included with UniDic Lite.
- OCR: RapidOCR, ONNX Runtime and PP-OCR models. Installed package licences are included.
  https://github.com/RapidAI/RapidOCR and https://github.com/PaddlePaddle/PaddleOCR
- UI: PySide6 / Qt. Distributed as dynamically loaded libraries; their licence texts are included.
  https://www.qt.io/licensing/
- Optional network services: MyMemory translation, JapanesePod101 recordings and Edge TTS.
  Downloaded audio is not bundled with the application.

Dictionary source URLs, release identifiers and download hashes are recorded in the included
`data` metadata. Sources and rebuild commands are available in this project's repository.
