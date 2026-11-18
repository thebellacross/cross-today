#!/bin/zsh
cd "$(dirname "$0")"
echo 'BELLACROSS local preview: http://127.0.0.1:8765'
echo 'Keep this window open. Press Control-C to stop.'
exec .venv/bin/python scripts/serve.py --album output/current
