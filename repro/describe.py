"""The header every reproducer prints: which interpreter this is, whether it carries a
patch from this repo, and whether it tracks a set built from a generator behind the
elements the generator creates (the order gh-152235 introduced)."""

import gc
import json
import pathlib
import sys


def free_threaded():
    return not getattr(sys, "_is_gil_enabled", lambda: True)()


def origin():
    exe = pathlib.Path(sys.executable)
    info = exe.parent / "build-info.txt"  # written by tools/build-cpython.sh
    if info.is_file():
        d = dict(line.split("=", 1) for line in info.read_text().splitlines() if "=" in line)
        patchset, mode = d.get("patchset", "none"), d.get("mode", "release")
        s = f"source build of {d.get('ref', '?')}, "
        s += "unpatched" if patchset == "none" else f"with patches/{patchset}"
        return s + ("" if mode == "release" else f", {mode}")
    if (exe.parent / "pybuilddir.txt").is_file():
        return f"source build in {exe.parent}"
    for meta in pathlib.Path(sys.prefix, "conda-meta").glob("python-[0-9]*.json"):
        channel = json.loads(meta.read_text()).get("channel", "")
        return f"{channel.rstrip('/').rsplit('/', 1)[-1] or 'conda'} build, unpatched"
    return "no patches from this repo"


def _made_elsewhere(n):
    # A generator made in a function: 3.15+ compiles a literal set(genexpr) inline.
    class E:
        pass
    return ((E(), i) for i in range(n))


def set_behind_elements():
    """Is set(gen) GC-tracked after the elements gen creates? None if free-threaded."""
    if free_threaded():
        return None
    gc.collect()
    gc.disable()
    try:
        s = set(_made_elsewhere(100))
        order, i = {}, 0
        for generation in (2, 1, 0):  # the order a full collection scans
            for o in gc.get_objects(generation=generation):
                order[id(o)] = i
                i += 1
        return order[id(s)] > min(order[id(e)] for e in s)
    finally:
        gc.enable()


def header(what, *notes):
    print(what)
    ft = " (free-threaded)" if free_threaded() else ""
    print(f"  Python {sys.version.split()[0]}{ft}: {origin()}")
    behind = set_behind_elements()
    if behind is None:
        print("  set(gen) order: n/a, free-threaded builds keep no GC list")
    elif behind:
        print("  set(gen) is GC-tracked behind its elements (gh-152235's change)")
    else:
        print("  set(gen) is GC-tracked ahead of its elements")
    for note in notes:
        print(f"  {note}")
    print(flush=True)
