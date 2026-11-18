#!/bin/zsh
cd -- "${0:A:h}"
echo 'Syncing selected audio from C_SoundSource. Original files stay unchanged.'
exec .venv/bin/python scripts/sync.py C_SoundSource --keychain
