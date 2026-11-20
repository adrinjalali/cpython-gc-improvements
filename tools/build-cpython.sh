#!/usr/bin/env bash
# Build CPython from a source archive, optionally patched, in .scratch/build/ (in-tree,
# not installed). Run it in the pixi "build" environment, which has the toolchain:
#
#   pixi run build-cpython REF [PATCHSET] [MODE]
#
#   REF       a tag such as v3.14.10, or a commit; "main" means the commit the
#             patches/main/* series apply to (see MAIN_COMMIT below)
#   PATCHSET  a directory under patches/ (main/gc-api, 3.14/tp-alloc, ...),
#             or "none" (the default)
#   MODE      release (default) | debug (--with-pydebug, assertions on)
#             | ft (--disable-gil) | ft-debug
#
# The interpreter ends up at .scratch/build/NAME/python, where NAME is REF, then the
# patch set's last path component, then MODE unless it is "release", joined with "-"
# (e.g. main-gc-api, v3.14.10-tp-alloc, main-revive-in-address-order-debug).
#
# Sources come from $CPYTHON_ARCHIVE/REF.tar.gz (default: GitHub's archive URL; point
# it at a mirror if GitHub is unreachable). All builds use configure's default flags
# (-O3, no PGO or LTO), so they compare with each other, not with release binaries.
set -euo pipefail

MAIN_COMMIT=4497fe9889105b1abc6d633971e84ee9f78bd3b8

ref=${1:?usage: build-cpython.sh REF [PATCHSET] [MODE]}
patchset=${2:-none}
mode=${3:-release}
here=$(cd "$(dirname "$0")/.." && pwd)
scratch=${SCRATCH:-$here/.scratch}
archive=${CPYTHON_ARCHIVE:-https://github.com/python/cpython/archive}

src_ref=$ref
[ "$ref" = main ] && src_ref=$MAIN_COMMIT
name=$ref
[ "$patchset" != none ] && name+="-$(basename "$patchset")"
[ "$mode" != release ] && name+="-$mode"
dir=$scratch/build/$name

mkdir -p "$scratch/src"
tarball=$scratch/src/$src_ref.tar.gz
if [ ! -s "$tarball" ]; then
  curl -fsSL --retry 3 -o "$tarball.part" "$archive/$src_ref.tar.gz"
  mv "$tarball.part" "$tarball"
fi

rm -rf "$dir" && mkdir -p "$dir"
tar xzf "$tarball" -C "$dir" --strip-components=1
cd "$dir"
if [ "$patchset" != none ]; then
  for p in "$here/patches/$patchset"/*.patch; do
    echo "applying $patchset/$(basename "$p")"
    patch -p1 --no-backup-if-mismatch --quiet < "$p"
  done
fi

flags=()
case $mode in
  release) ;;
  debug) flags+=(--with-pydebug) ;;
  ft) flags+=(--disable-gil) ;;
  ft-debug) flags+=(--disable-gil --with-pydebug) ;;
  *) echo "unknown MODE $mode" >&2; exit 2 ;;
esac

# conda-forge has no libb2, so leave blake2 to OpenSSL; otherwise configure can find a
# host libb2.pc whose header the conda compiler's sysroot doesn't have.
CC=gcc \
CPPFLAGS="-I$CONDA_PREFIX/include" \
LDFLAGS="-L$CONDA_PREFIX/lib -Wl,-rpath,$CONDA_PREFIX/lib" \
PKG_CONFIG_LIBDIR="$CONDA_PREFIX/lib/pkgconfig:$CONDA_PREFIX/share/pkgconfig" \
  ./configure --with-openssl="$CONDA_PREFIX" \
    --with-builtin-hashlib-hashes=md5,sha1,sha2,sha3 "${flags[@]}" > configure.log 2>&1
make -j"${JOBS:-$(nproc)}" > make.log 2>&1
./python -c 'import sys; print(sys.version)'
echo "built $dir/python"
