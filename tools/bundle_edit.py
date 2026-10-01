#!/usr/bin/env python3
"""Decode / re-encode the index.html bundle without hand-editing escaped strings.

    python3 tools/bundle_edit.py decode [--work DIR]   # index.html -> DIR/template.html, DIR/assets/*, DIR/meta.json
    python3 tools/bundle_edit.py encode [--work DIR]   # DIR -> index.html (only changed parts are rewritten)
    python3 tools/bundle_edit.py check                 # decode + encode in memory, assert byte-identical

The template is the JSON string inside <script type="__bundler/template">, encoded as
json.dumps(text) with "</" written as "<\\u002F". Manifest assets are gzip+base64; gzip output is
not reproducible, so an asset is re-compressed only when its decoded bytes changed, otherwise
its original base64 is kept. Stdlib only. Work files default to /tmp/satellario-bundle.
"""
import argparse
import base64
import gzip
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "index.html")
EXT = {"text/javascript": ".js", "font/woff2": ".woff2", "text/css": ".css", "image/svg+xml": ".svg", "image/png": ".png"}


def _lines():
    with open(INDEX, encoding="utf-8") as f:
        return f.read().split("\n")


def _locate(lines):
    """Return line indexes of the manifest JSON and the template JSON (each sits on one line)."""
    man = lines.index('  <script type="__bundler/manifest">') + 1
    tpl = lines.index('  <script type="__bundler/template">') + 1
    return man, tpl


def enc_template(text):
    return json.dumps(text).replace("</", "<\\u002F")


def enc_manifest(m):
    return json.dumps(m, separators=(",", ":"))


def _raw_bytes(entry):
    b = base64.b64decode(entry["data"])
    return gzip.decompress(b) if entry.get("compressed") else b


def decode(work):
    lines = _lines()
    mi, ti = _locate(lines)
    manifest = json.loads(lines[mi])
    template = json.loads(lines[ti])
    os.makedirs(os.path.join(work, "assets"), exist_ok=True)
    with open(os.path.join(work, "template.html"), "w", encoding="utf-8") as f:
        f.write(template)
    meta = {}
    for uuid, entry in manifest.items():
        raw = _raw_bytes(entry)
        name = uuid + EXT.get(entry["mime"], ".bin")
        with open(os.path.join(work, "assets", name), "wb") as f:
            f.write(raw)
        meta[uuid] = {"file": name, "sha256": hashlib.sha256(raw).hexdigest()}
    with open(os.path.join(work, "meta.json"), "w") as f:
        json.dump(meta, f, indent=1)
    print("decoded to", work, "(%d assets)" % len(meta))


def build(work, lines):
    mi, ti = _locate(lines)
    manifest = json.loads(lines[mi])
    with open(os.path.join(work, "meta.json")) as f:
        meta = json.load(f)
    changed = []
    for uuid, info in meta.items():
        with open(os.path.join(work, "assets", info["file"]), "rb") as f:
            raw = f.read()
        if hashlib.sha256(raw).hexdigest() != hashlib.sha256(_raw_bytes(manifest[uuid])).hexdigest():
            data = gzip.compress(raw, mtime=0) if manifest[uuid].get("compressed") else raw
            manifest[uuid]["data"] = base64.b64encode(data).decode()
            changed.append(info["file"])
    with open(os.path.join(work, "template.html"), encoding="utf-8") as f:
        template = f.read()
    out = list(lines)
    out[mi] = enc_manifest(manifest)
    out[ti] = enc_template(template)
    return out, changed


def encode(work):
    lines = _lines()
    out, changed = build(work, lines)
    with open(INDEX, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("encoded index.html; re-compressed assets:", changed or "none",
          "| template changed:", out[_locate(lines)[1]] != lines[_locate(lines)[1]])


def check():
    import tempfile
    lines = _lines()
    with tempfile.TemporaryDirectory() as work:
        decode(work)
        out, changed = build(work, lines)
    ok = out == lines and not changed
    print("round-trip byte-identical:", ok)
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["decode", "encode", "check"])
    ap.add_argument("--work", default="/tmp/satellario-bundle")
    a = ap.parse_args()
    sys.exit({"decode": lambda: decode(a.work), "encode": lambda: encode(a.work), "check": check}[a.cmd]() or 0)
