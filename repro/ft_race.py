"""Why gh-152235 was needed: a half-built set shared with another thread.

Free-threaded builds only. Before gh-152235 (3.13.14t, 3.14.6t and older),
set(iterable) and frozenset(iterable) GC-tracked the new set *before* filling it, and the fill takes no lock: it assumes
nobody else can see the set yet (set_update_local asserts Py_REFCNT == 1). But code
the fill runs, here the generator, can find the set with gc.get_objects() and give
it to another thread, which then reads it while the fill resizes it: the old table
is freed under the reader.

    python repro/ft_race.py [--kind set|frozenset] [--rounds 200]

Exit status: 0 = never saw the half-built set, 1 = saw it and read inconsistent
state, or the process crashes (SIGSEGV, exit -11).
"""

import argparse
import gc
import sys
import threading


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["set", "frozenset"], default="frozenset")
    ap.add_argument("--rounds", type=int, default=200)
    ap.add_argument("-n", type=int, default=50_000)
    a = ap.parse_args()
    build = set if a.kind == "set" else frozenset
    from describe import header
    header(f"Can another thread reach a half-built {a.kind}? ({a.rounds} rounds)",
           "Before gh-152235 it can, and reads it while the fill resizes it,",
           "which can crash the process (exit 139 = segfault).")
    if getattr(sys, "_is_gil_enabled", lambda: True)():
        print("note: GIL enabled; this needs a free-threaded build to race")

    box = []
    stop = threading.Event()
    oddities = []

    def reader():
        while not stop.is_set():
            if not box:
                continue
            s = box[0]
            try:
                before = len(s)
                items = list(s)  # walks the table while the fill may resize it
                after = len(s)
                if before != after:
                    oddities.append(("changed while read", before, after))
                for x in items:
                    if type(x) is not int and x is not marker:
                        oddities.append(("garbage element", type(x).__name__))
                        break
            except Exception as e:  # noqa: BLE001
                oddities.append(("exception", repr(e)))

    marker = object()
    seen = 0

    def gen(n):
        nonlocal seen
        yield marker
        # Find the set being built: it is the only one holding `marker`.
        for o in gc.get_objects():
            if type(o) is build and marker in o:
                box.append(o)
                seen += 1
                break
        yield from range(n)

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    for _ in range(a.rounds):
        box.clear()
        build(gen(a.n))
    stop.set()
    t.join(timeout=5)
    print(f"{sys.version.split()[0]} {a.kind}: leaked the half-built set in "
          f"{seen}/{a.rounds} rounds; inconsistent reads: {len(oddities)}"
          + (f" e.g. {oddities[:3]}" if oddities else ""))
    sys.exit(1 if seen else 0)


if __name__ == "__main__":
    main()
