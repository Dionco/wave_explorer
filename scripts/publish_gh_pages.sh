#!/usr/bin/env bash
# Publish the prebuilt static demo (site/) to the gh-pages branch.
# Payloads must already be exported (scripts/export_demo.py) and committed/present.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
test -f site/index.html || { echo "site/index.html missing — build first"; exit 1; }
test -f site/payload/manifest.json || { echo "payloads missing — run export_demo.py"; exit 1; }
# site/ must be committed so its tree object exists.
git add site && git commit -m "build: refresh static demo site" || echo "nothing to commit"
# Publish without git-subtree (not always installed): make a root commit whose
# tree IS site/ (so index.html lands at the gh-pages root), then force-push it.
site_tree="$(git rev-parse HEAD:site)"
publish_commit="$(git commit-tree "$site_tree" -m "Publish static demo ($(git rev-parse --short HEAD))")"
git push -f origin "$publish_commit:refs/heads/gh-pages"
echo "Published. URL: https://dionco.github.io/wave_explorer/"
