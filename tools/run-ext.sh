#!/usr/bin/env bash
# Build ext/csetsub.c against one interpreter and run ext/check_csetsub.py with it.
# Run it in the pixi "build" environment (for the compiler):
#
#   pixi run -e build bash tools/run-ext.sh /path/to/python
set -euo pipefail
py=$1
here=$(cd "$(dirname "$0")/.." && pwd)
out=${SCRATCH:-$here/.scratch}/ext/$(echo "$py" | md5sum | cut -c1-8)
mkdir -p "$out"
inc=$("$py" -c 'import sysconfig; print(sysconfig.get_paths()["include"])')
cfg=$("$py" -c 'import sysconfig; print(sysconfig.get_config_h_filename().rsplit("/", 1)[0])')
suffix=$("$py" -c 'import sysconfig; print(sysconfig.get_config_var("EXT_SUFFIX"))')
gcc -shared -fPIC -O1 -I"$inc" -I"$cfg" "$here/ext/csetsub.c" -o "$out/csetsub$suffix"
printf '%s: ' "$("$py" -c 'import sys; print(sys.version.split()[0])')"
PYTHONPATH=$out "$py" "$here/ext/check_csetsub.py" | tr '\n' ' '
echo
