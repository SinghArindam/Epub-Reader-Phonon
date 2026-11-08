#!/usr/bin/env python3
"""
Aura ePub Reader builder.

Downloads the runtime libraries, the Phonon browser package, and the Phonon
31M checkpoint, then produces `reader.standalone.html`: one HTML file with
the app, ePub engine, voices, WebAssembly runtime, and model weights embedded.

Usage:
    python build.py

The first run downloads about 70 MB. Everything is cached in `.cache/` and
`vendor/`, so later runs only rebuild the HTML.

Requirements: Python 3.8+ and nothing outside the standard library.
"""

from __future__ import annotations

import base64
import io
import json
import re
import sys
import tarfile
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / ".cache"
VENDOR_DIR = BASE_DIR / "vendor"
PHONON_DIR = VENDOR_DIR / "phonon-tts"
MODEL_DIR = VENDOR_DIR / "phonon-model"

SOURCE_HTML = BASE_DIR / "index.html"
OUTPUT_HTML = BASE_DIR / "reader.standalone.html"

JSZIP_URL = "https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"
EPUBJS_URL = "https://cdn.jsdelivr.net/npm/epubjs@0.3.93/dist/epub.min.js"

PHONON_VERSION = "0.6.0"
PHONON_TARBALL = f"https://registry.npmjs.org/phonon-tts/-/phonon-tts-{PHONON_VERSION}.tgz"

MODEL_REPO = "gradium/phonon-31m-en"
MODEL_COMMIT = "92741c5b07d085ff840e26fea8ce43110b87852f"
MODEL_FILES = [
    "config.json",
    "tokenizer.json",
    "model.q8.gguf",
    "default-voice.safetensors",
]

# Everything the standalone file needs from the phonon-tts package.
PHONON_FILES = [
    "index.js",
    "hub.js",
    "wav.js",
    "fetch.js",
    "device.js",
    "threads.js",
    "simd.js",
    "worker.js",
    "wasm/phonon_tts.js",
    "wasm/phonon_tts_bg.wasm",
    "wasm/phonon_tts_simd_bg.wasm",
]

USER_AGENT = "Aura-ePub-Reader-Builder/1.0 (+https://github.com)"

# Windows terminals still default to a legacy code page; keep the progress
# output readable instead of failing on an arrow.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover - older interpreters
    pass


def log(message: str) -> None:
    print(message, flush=True)


def download(url: str, destination: Path, label: str | None = None) -> Path:
    """Download `url` to `destination`, reusing a non-empty cached copy."""
    if destination.exists() and destination.stat().st_size > 0:
        log(f"  = {label or destination.name} (cached)")
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    log(f"  ↓ {label or destination.name}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request) as response:
        total = int(response.headers.get("Content-Length") or 0)
        received = 0
        with open(destination, "wb") as out:
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
                received += len(chunk)
                if total:
                    pct = received * 100 // total
                    print(f"\r    {pct:3d}%  ({received / 1048576:.1f} MB)", end="", flush=True)
        if total:
            print()
    return destination


def ensure_vendor_files() -> None:
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    log("→ Runtime libraries")
    download(JSZIP_URL, VENDOR_DIR / "jszip.min.js")
    download(EPUBJS_URL, VENDOR_DIR / "epub.min.js")

    log("→ Phonon browser package")
    tarball = download(PHONON_TARBALL, CACHE_DIR / f"phonon-tts-{PHONON_VERSION}.tgz")
    with tarfile.open(tarball, "r:gz") as archive:
        members = {member.name: member for member in archive.getmembers()}
        for name in PHONON_FILES:
            member = members.get("package/" + name)
            if member is None:
                raise RuntimeError(f"phonon-tts package is missing {name}")
            target = PHONON_DIR / name
            target.parent.mkdir(parents=True, exist_ok=True)
            extracted = archive.extractfile(member)
            if extracted is None:
                raise RuntimeError(f"could not read {name} from the package")
            target.write_bytes(extracted.read())
        # Keep the licence notices next to the vendored code.
        for licence in ("LICENSE-MIT", "LICENSE-APACHE", "THIRD_PARTY_LICENSES.md"):
            member = members.get("package/" + licence)
            if member is not None:
                extracted = archive.extractfile(member)
                if extracted is not None:
                    (PHONON_DIR / licence).write_bytes(extracted.read())
    log("  = phonon-tts files extracted")

    log("→ Phonon 31M checkpoint (Apache 2.0)")
    for filename in MODEL_FILES:
        url = f"https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_COMMIT}/{filename}"
        download(url, MODEL_DIR / filename, label=filename)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def escape_script(content: str) -> str:
    """Keep embedded JavaScript from closing its own <script> element."""
    return re.sub(r"</script", r"<\\/script", content, flags=re.IGNORECASE)


def inline_tag(html: str, src: str, content: str) -> str:
    replacement = "<script>\n/* Embedded by build.py: " + src + " */\n" + escape_script(content) + "\n</script>"
    pattern = re.compile(
        r"<script[^>]*src=[\"']" + re.escape(src) + r"[\"'][^>]*>\s*</script>",
        re.IGNORECASE,
    )
    html, count = pattern.subn(lambda _: replacement, html, count=1)
    if count == 0:
        raise RuntimeError(f"could not find <script src=\"{src}\"> in index.html")
    return html


def build_phonon_loader() -> str:
    """Return a classic script that embeds the package and the checkpoint."""
    assets: dict[str, str] = {}

    for name in PHONON_FILES:
        path = PHONON_DIR / name
        if not path.exists():
            raise RuntimeError(f"missing vendor file: {path}")
        assets[name] = base64.b64encode(path.read_bytes()).decode("ascii")

    for name in MODEL_FILES:
        path = MODEL_DIR / name
        if not path.exists():
            raise RuntimeError(f"missing model file: {path}")
        assets[name] = base64.b64encode(path.read_bytes()).decode("ascii")

    payload = json.dumps(assets, separators=(",", ":"))
    model_files = json.dumps(MODEL_FILES)
    phonon_files = json.dumps(PHONON_FILES)

    return r"""
/*
 * Embedded Phonon runtime.
 *
 * Every module, WebAssembly binary, and model file below is carried inside
 * this HTML as base64. At start-up the modules are rewritten so their imports
 * point at Blob URLs, then the worker and the model are created from those
 * same Blob URLs. Nothing is fetched from the network.
 */
(function () {
  'use strict';

  var ASSETS = __ASSETS__;
  var PHONON_FILES = __PHONON_FILES__;
  var MODEL_FILES = __MODEL_FILES__;

  var instance = null;
  var loading = null;
  var decoded = {};
  var moduleUrls = {};
  var wasmUrls = {};
  var modelUrls = {};

  function bytes(name) {
    if (decoded[name]) return decoded[name];
    var raw = atob(ASSETS[name]);
    var out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    decoded[name] = out;
    return out;
  }

  function text(name) {
    return new TextDecoder().decode(bytes(name));
  }

  function blob(name, type) {
    return URL.createObjectURL(new Blob([bytes(name)], { type: type }));
  }

  function resolvePath(base, spec) {
    var parts = base.split('/');
    parts.pop();
    spec.split('/').forEach(function (part) {
      if (part === '..') parts.pop();
      else if (part !== '.' && part !== '') parts.push(part);
    });
    return parts.join('/');
  }

  function rewriteImports(name, source) {
    // A Blob URL is not a hierarchical base: new URL('./x', import.meta.url)
    // throws inside the worker. The loader always passes explicit Blob URLs
    // for the worker and the wasm builds, so the relative fallbacks can go.
    source = source.replace(/new URL\(\s*(['"])\.{1,2}\/[^'"]+\1\s*,\s*import\.meta\.url\s*\)/g, "'about:blank'");

    var staticPattern = /(from\s*['"])(\.{1,2}\/[^'"]+)(['"])/g;
    source = source.replace(staticPattern, function (match, before, spec, after) {
      var target = resolvePath(name, spec);
      if (PHONON_FILES.indexOf(target) === -1) return match;
      return before + makeModule(target) + after;
    });

    if (name === 'worker.js') {
      var dynamicPattern = /(import\s*\(\s*['"])(\.{1,2}\/[^'"]+)(['"]\s*\))/g;
      source = source.replace(dynamicPattern, function (match, before, spec, after) {
        var target = resolvePath(name, spec);
        if (PHONON_FILES.indexOf(target) === -1) return match;
        return before + makeModule(target) + after;
      });
    }
    return source;
  }

  function makeModule(name) {
    if (moduleUrls[name]) return moduleUrls[name];
    var source = text(name);
    source = rewriteImports(name, source);
    moduleUrls[name] = URL.createObjectURL(new Blob([source], { type: 'text/javascript' }));
    return moduleUrls[name];
  }

  function wasmUrl(name) {
    if (!wasmUrls[name]) wasmUrls[name] = blob(name, 'application/wasm');
    return wasmUrls[name];
  }

  function modelUrl(name) {
    if (!modelUrls[name]) modelUrls[name] = blob(name, 'application/octet-stream');
    return modelUrls[name];
  }

  function modelSpec() {
    return {
      weights: { q8: modelUrl('model.q8.gguf') },
      tokenizer: modelUrl('tokenizer.json'),
      config: modelUrl('config.json'),
      voices: { default: modelUrl('default-voice.safetensors') },
      defaultVoice: 'default'
    };
  }

  async function getTTS(onProgress) {
    if (instance) return instance;
    if (loading) return loading;

    loading = (async function () {
      var mod = await import(makeModule('index.js'));
      instance = await mod.PhononTTS.load({
        lang: 'en',
        model: modelSpec(),
        quant: 'q8',
        device: 'auto',
        threads: 1,
        cache: false,
        workerUrl: makeModule('worker.js'),
        wasmUrl: wasmUrl('wasm/phonon_tts_bg.wasm'),
        simdWasmUrl: wasmUrl('wasm/phonon_tts_simd_bg.wasm'),
        onProgress: onProgress
      });
      return instance;
    })();

    return loading;
  }

  // Release the decoded copies once the model has consumed them.
  function releaseAssets() {
    decoded = {};
    modelUrls = {};
  }

  window.PhononRuntime = {
    getTTS: getTTS,
    get instance() { return instance; },
    get loading() { return loading; },
    isReady: function () { return !!instance; },
    modelSpec: modelSpec,
    releaseAssets: releaseAssets
  };
})();
""".replace("__ASSETS__", payload).replace("__PHONON_FILES__", phonon_files).replace("__MODEL_FILES__", model_files)


def build() -> None:
    ensure_vendor_files()

    log("→ Reading source")
    if not SOURCE_HTML.exists():
        raise SystemExit(f"[Error] {SOURCE_HTML.name} not found")

    html = read_text(SOURCE_HTML)

    log("→ Embedding ePub engine")
    html = inline_tag(html, "./vendor/jszip.min.js", read_text(VENDOR_DIR / "jszip.min.js"))
    html = inline_tag(html, "./vendor/epub.min.js", read_text(VENDOR_DIR / "epub.min.js"))

    log("→ Embedding Phonon runtime and checkpoint")
    loader = build_phonon_loader()
    pattern = re.compile(
        r"<script[^>]*src=[\"']\./phonon-runtime\.js[\"'][^>]*>\s*</script>",
        re.IGNORECASE,
    )
    replacement = "<script>\n" + escape_script(loader) + "\n</script>"
    html, count = pattern.subn(lambda _: replacement, html, count=1)
    if count == 0:
        raise SystemExit("[Error] could not find <script src=\"./phonon-runtime.js\"> in index.html")

    OUTPUT_HTML.write_text(html, encoding="utf-8", newline="\n")
    size_mb = OUTPUT_HTML.stat().st_size / 1048576
    log(f"✓ Created {OUTPUT_HTML.name} ({size_mb:.1f} MB)")
    log("  Open it directly in a browser. No server, network, or install needed.")


if __name__ == "__main__":
    try:
        build()
    except KeyboardInterrupt:
        sys.exit(130)
