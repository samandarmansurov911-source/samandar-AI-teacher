#!/usr/bin/env bash
# Mock fayllaridan HTML va PDF yig'adi: ./build.sh
set -euo pipefail
cd "$(dirname "$0")"
pandoc -f markdown+hard_line_breaks -s --embed-resources --css style.css \
  --metadata lang=uz -o multilevel_writing_9_mocks.html intro.md mock{1..9}.md
CHROME="${CHROME:-$(ls -d /opt/pw-browsers/chromium-*/chrome-linux/chrome 2>/dev/null | head -1)}"
"$CHROME" --headless --no-sandbox --disable-gpu --no-pdf-header-footer \
  --print-to-pdf=multilevel_writing_9_mocks.pdf "file://$PWD/multilevel_writing_9_mocks.html"
