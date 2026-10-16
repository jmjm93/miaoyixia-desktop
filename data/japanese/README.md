# Japanese dictionary

JMdict is copyright the Electronic Dictionary Research and Development Group
([EDRDG](https://www.edrdg.org/)), distributed under
[Creative Commons Attribution-ShareAlike 4.0](https://www.edrdg.org/edrdg/licence.html).
The full licence is included in `licence.html`.

The English release is provided by
[jmdict-simplified](https://github.com/scriptin/jmdict-simplified).
`meta.json` records the release, source URL, SHA-256 and entry count.
`jmdict.sqlite3` preserves original entries and adds an exact-form lookup index.

Rebuild using `.venv\Scripts\python.exe tools/setup_japanese.py`.
Update using `.venv\Scripts\python.exe tools/setup_japanese.py --update`, then restart.
Japanese morphology uses Fugashi and UniDic Lite; their distributions include their licences.
