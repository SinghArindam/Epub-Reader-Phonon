# Aura — ePub Reader with Phonon TTS

A single-file, offline ePub reader. Text-to-speech runs on the device with
[Phonon 31M](https://huggingface.co/gradium/phonon-31m-en) compiled to
WebAssembly — no server, no API key, no network after the build step.

The interface follows the design rules from the project brief: AMOLED-first
dark mode, crisp light and warm sepia themes, hairline borders, spring easing,
and lightweight microinteractions.

## What it does

- Opens `.epub` files by picker or drag and drop, plus a built-in sample book.
- Reads with **Phonon 31M** through `phonon-tts` (WebGPU when available, CPU
  otherwise), streaming 24 kHz audio sentence by sentence.
- Highlights the sentence being spoken and advances through pages and chapters
  automatically.
- Table of contents, reading progress, font size, serif/sans/mono typefaces,
  light/sepia/AMOLED themes, and 0.75×–2× playback speed.
- Lock-screen controls through the Media Session API.
- Optional system-voice fallback if Phonon cannot start on a device.

## Build the standalone file

```bash
python build.py
```

The first run downloads about 70 MB (ePub engine, Phonon package, and the
Phonon 31M q8 checkpoint). Everything is cached under `.cache/` and `vendor/`,
so later runs only rebuild the HTML.

The result is **`reader.standalone.html`** — one file containing:

- the app UI and the ePub engine (JSZip + epub.js),
- the `phonon-tts` ES modules and both WebAssembly builds,
- `config.json`, `tokenizer.json`, `model.q8.gguf`, and the default voice.

Open it directly from disk. It works from `file://` with no server and no
network connection.

## Develop with the vendor folder

`build.py` also populates `vendor/`:

```
vendor/
├── jszip.min.js
├── epub.min.js
├── phonon-tts/          # phonon-tts npm package
└── phonon-model/        # Phonon 31M files
```

Because `index.html` uses ES modules and a module worker, serve it over HTTP
during development:

```bash
python -m http.server 8000
# open http://localhost:8000/
```

## Project layout

```
index.html             # App UI + reader logic (source)
phonon-runtime.js      # Development Phonon loader (vendor/ URLs)
build.py               # Downloads dependencies and builds reader.standalone.html
reader.standalone.html # Generated single-file build
vendor/                # Generated dependencies (git-ignored)
.cache/                # Generated download cache (git-ignored)
```

## GitHub Pages

The app is already laid out to be served from the repository root: `index.html`
plus the committed `vendor/` folder. Enable Pages once under **Settings → Pages
→ Source: Deploy from a branch → `main` → `/ (root)`**.

Size notes:

- `vendor/phonon-model/model.q8.gguf` is 61.5 MB. GitHub warns for files over
  50 MB but accepts anything under 100 MB, so a normal push works.
- The whole site is about 71 MB; the Pages limit is 1 GB.
- The first visit downloads the checkpoint once, then the browser keeps it in
  the Cache API. Later visits start from cache.

If you would rather avoid committing 71 MB, keep using the generated
`reader.standalone.html` locally: it needs no server at all.

## Licences

- Phonon 31M weights: Apache 2.0 (Gradium).
- `phonon-tts`: MIT OR Apache-2.0.
- epub.js: BSD-3-Clause.
- JSZip: MIT.

The included sample book is original text written for this demo.
