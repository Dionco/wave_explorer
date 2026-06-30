#!/usr/bin/env bash
# Publish the prebuilt static demo (site/) to the gh-pages branch.
# Payloads must already be exported (scripts/export_demo.py) and committed/present.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
test -f site/index.html || { echo "site/index.html missing — build first"; exit 1; }
test -f site/payload/manifest.json || { echo "payloads missing — run export_demo.py"; exit 1; }
# git subtree push requires site/ to be committed on the current branch.
git add site && git commit -m "build: refresh static demo site" || echo "nothing to commit"
git subtree split --prefix site -b gh-pages-tmp
git push -f origin gh-pages-tmp:gh-pages
git branch -D gh-pages-tmp
echo "Published. URL: https://dionco.github.io/wave_explorer/"
