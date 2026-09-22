#!/bin/sh
set -eu

bin_dir="$HOME/.local/bin"
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

mkdir -p "$bin_dir"
cp "$script_dir/lamzu_ctl.py" "$bin_dir/lamzu"
chmod 755 "$bin_dir/lamzu"

echo "Installed lamzu to $bin_dir/lamzu"
case ":$PATH:" in
    *":$bin_dir:"*) ;;
    *) echo "Add $bin_dir to PATH to run 'lamzu' directly." ;;
esac
