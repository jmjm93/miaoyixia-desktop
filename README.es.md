# 瞄一下

[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](#ejecutar-desde-el-código-fuente)
[![Licencia: MIT](https://img.shields.io/badge/licencia-MIT-blue)](LICENSE)

[English](README.md) | Español

Lee chino en cualquier parte de la pantalla: selecciona una región para detectar frases nuevas continuamente o haz una captura puntual. Incluye integración con Anki para crear tarjetas fácilmente y opciones de configuración. También es compatible con el japonés, porque ¿por qué no?

Disponible tanto en inglés como en español.

## Instalación

**Windows 10/11 de 64 bits:** descarga `Miaoyixia-windows-x64.zip` desde las descargas de las versiones del repositorio, extrae la carpeta completa y abre **Miaoyixia.exe**. No necesitas instalar Python.
La aplicación empaquetada incluye reconocimiento de chino y japonés y diccionarios en inglés y español.
La configuración y los registros se guardan en `%LOCALAPPDATA%\Miaoyixia`. Anki/AnkiConnect, la traducción por internet y el audio son opcionales; el reconocimiento de texto (OCR) y las definiciones funcionan sin conexión.

### Ejecutar desde el código fuente

Instala **Python 3.11 de 64 bits**, descarga o clona este proyecto y haz doble clic en **setup.cmd**.
Después, inicia la aplicación con **run.cmd**. Para instalarla manualmente, abre una terminal en la carpeta del proyecto y ejecuta:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Para el japonés, ejecuta también:

```powershell
.venv\Scripts\python.exe tools/setup_japanese.py
```

Para las definiciones en español, ejecuta también `.venv\Scripts\python.exe tools/setup_spanish.py`.

La primera captura puede tardar más mientras la aplicación descarga lo necesario. Se necesita conexión a internet para la instalación, la traducción y la descarga de audio para Anki.

## Iniciar la aplicación

Abre **Miaoyixia.exe** desde la carpeta de la versión descargada, o **run.cmd** si la ejecutas desde el código fuente.
Para diagnosticar problemas al ejecutar desde el código fuente, usa **run-console.cmd** para ver los mensajes de error.

La aplicación permanece en la bandeja del sistema al cerrar la ventana principal. Elige **Salir** en la ventana o en el menú de la bandeja para cerrarla por completo.

## Uso

- **Opciones:** elige chino o japonés para las nuevas capturas. Las regiones ya fijadas conservan su idioma.
- **Idioma del usuario:** elige English o Español en Opciones para la interfaz, las definiciones y la traducción de frases. Si falta una definición en español, se muestra en inglés; Anki guarda las definiciones que aparecen en pantalla.
- **Captura puntual · Ctrl+Shift+Space:** arrastra para dibujar un recuadro alrededor del texto que quieras leer.
- **Observar una región · Ctrl+Shift+W:** fija una zona para leer automáticamente el texto nuevo.
- **Modo manual:** pulsa **A** en la ventana de resultados para cambiar a **M** y, después, pulsa el botón para volver a escanear o **Ctrl+Shift+R** cuando quieras una nueva lectura. Pulsa **M** para volver al modo automático.
- **Definiciones:** haz clic en una palabra para ver su lectura y significado. Puedes editar el texto reconocido y pulsar Intro para corregirlo.
- **Traducción:** usa el icono de traducción de la ventana de resultados para activar o desactivar la traducción en línea.
- **Anki:** abre Opciones y selecciona la pestaña de Anki para chino o japonés para activar la exportación y configurar el mazo, el tipo de nota, los campos y el audio. Con Anki y AnkiConnect en ejecución, pulsa **+ Anki** junto a una definición.

En **config.json** encontrarás ajustes adicionales, como el atajo para volver a escanear y el mazo, el tipo de nota y los campos de Anki. Los cambios guardados se aplican mientras la aplicación está en ejecución.

Créditos y licencia del diccionario japonés: [JMdict / EDRDG](data/japanese/README.md).

Para crear la versión de Windows desde el código fuente, instala ambos diccionarios y ejecuta
`powershell -ExecutionPolicy Bypass -File build-windows.ps1`. El archivo ZIP se guarda en `dist`.
Los archivos intermedios se guardan en `build-artifacts`; ejecuta la aplicación desde `dist/Miaoyixia`.
También puedes compilarla con GitHub Actions mediante **Windows x64 release → Run workflow**, o con una etiqueta `v*`;
descarga el ZIP de los artefactos de esa ejecución y adjúntalo a tu versión de GitHub.

## Licencia

El código fuente original de este proyecto se publica bajo la [licencia MIT](LICENSE).
Puedes usarlo, modificarlo, distribuirlo y venderlo, incluso en proyectos de código
cerrado, siempre que conserves el aviso de copyright y la licencia en las copias
o partes sustanciales del software. Esto se aplica tanto a la distribución comercial
como a la no comercial; no es obligatorio publicar tus cambios. El software se proporciona sin garantía.
Los componentes de terceros y los datos de los diccionarios tienen sus propias licencias; consulta los
[avisos de terceros](THIRD_PARTY_NOTICES.md) para más información.
