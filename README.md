<h1 align="center">瞄一下</h1>

<p align="center">
  <a href="#running-from-source"><img src="https://img.shields.io/badge/Python-3.11-3776AB?logo=python&amp;logoColor=white" alt="Python 3.11"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License: MIT"></a>
</p>

<p align="center">
  English | <a href="README.es.md">Español</a>
</p>

https://github.com/user-attachments/assets/05fee695-1976-482d-81fc-7a5cff07c02b

Read Chinese anywhere on your screen, set a region to continually scan new sentences, or just do a one-time scan. Anki integration to easily create flashcards. Configurable. Also Japanese compatibility because why not.



Both for English and Spanish.

## Setup

**Windows 10/11 x64:** download `Miaoyixia-windows-x64.zip` from the repository's release
downloads, extract the entire folder, and open **Miaoyixia.exe**. Python is not required.
The packaged app includes Chinese/Japanese recognition and English/Spanish dictionaries.
Settings and logs are stored in `%LOCALAPPDATA%\Miaoyixia`. Anki/AnkiConnect and internet-based
translation or audio are optional; OCR and definitions work offline.

### Running from source

Install **Python 3.11 x64**, download or clone this project, and double-click **setup.cmd**.
Then launch with **run.cmd**. To set up manually, open a terminal in the project folder and run:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

For Japanese, also run:

```powershell
.venv\Scripts\python.exe tools/setup_japanese.py
```

For Spanish definitions, also run `.venv\Scripts\python.exe tools/setup_spanish.py`.

The first capture may take longer while the app downloads what it needs. Internet access is needed for setup, translation, and downloading Anki audio.

## Run

Open **Miaoyixia.exe** from the extracted release folder, or **run.cmd** when running from source.
For source troubleshooting, use **run-console.cmd** to see error messages.

The app stays in the system tray when you close its main window. Choose **Quit** from the window or tray menu to exit.

## Use

- **Options:** choose Chinese or Japanese for new captures. Existing pinned regions keep their language.
- **User language:** choose English or Español in Options for the interface, definitions, and sentence translation. Missing Spanish definitions fall back to English; Anki saves the displayed definitions.
- **Snip once · Ctrl+Shift+Space:** drag a box around the text you want to read.
- **Watch a region · Ctrl+Shift+W:** pin an area and read new text automatically.
- **Manual mode:** click **A** in the result window to switch to **M**, then click Rescan or press **Ctrl+Shift+R** when you want a new reading. Click **M** to return to automatic mode.
- **Definitions:** click a word to see its reading and meaning. Edit recognized text and press Enter to correct it.
- **Translation:** use the translation icon in the result window to turn online translation on or off.
- **Anki:** open Options and select the Chinese or Japanese Anki tab to enable export and configure the deck, note type, fields, and audio. With Anki and AnkiConnect running, click **+ Anki** beside a definition.

Additional settings, including the rescan hotkey and Anki deck, note type, and fields, are in **config.json**. Saved changes apply while the app is running.

Japanese dictionary credits and licence: [JMdict / EDRDG](data/japanese/README.md).

To build the Windows release from source, install both dictionaries and run
`powershell -ExecutionPolicy Bypass -File build-windows.ps1`. The ZIP is written to `dist`.
Intermediate build files are stored in `build-artifacts`; run the app from `dist/Miaoyixia`.
GitHub Actions can also build it with **Windows x64 release → Run workflow**, or a `v*` tag;
download the ZIP from that run's artifacts and attach it to your GitHub release.

## License

This project's original source code is released under the [MIT License](LICENSE).
You may use, modify, distribute, and sell it, including in closed-source projects,
provided you retain the copyright and license notice in copies or substantial
portions of the software. This applies to both commercial and noncommercial
distribution; publishing your changes is not required. The software is provided without warranty.
Third-party components and dictionary data have their own licenses; see
[Third-party notices](THIRD_PARTY_NOTICES.md) for details.
