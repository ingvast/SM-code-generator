#!/bin/bash
set -e
if command -v uv &>/dev/null; then
    uv tool install "$(dirname "$0")/dist/smbuilder-0.2.1-py3-none-any.whl"
else
    pip install "$(dirname "$0")/dist/smbuilder-0.2.1-py3-none-any.whl"
fi
echo "sm-compiler installed. Run: sm-compiler --help"
