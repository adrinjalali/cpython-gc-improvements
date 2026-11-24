"""Which containers and build patterns make later full collections slow?

    python repro/other_types.py [-n 1000000]

Same measurement as gc_order_perf.py (a full gc.collect() after the first one that
follows the build), for other container types and for sets built from existing
objects. Elements are GC-tracked: (K(), i) tuples for set-likes, K() values for
dict-likes. Each row is compared with s.update(gen), which builds the same set but
tracks it before its elements.
"""

import argparse
import builtins
import gc
import statistics
import time

from describe import header


class K:
    __slots__ = ("v",)

    def __init__(self, v):
        self.v = v


def pairs(n):
    return ((K(i), i) for i in range(n))


BASELINE = "s.update(gen)"

PATTERNS = {
    # set-likes (traversed in hash order); the baseline first
    BASELINE: lambda n: (s := set(), s.update(pairs(n)), s)[2],
    "set(gen)": lambda n: set(pairs(n)),
    "set([listcomp]) (list dropped)": lambda n: set([(K(i), i) for i in range(n)]),
    "frozenset(tuple(gen))": lambda n: frozenset(tuple(pairs(n))),
    # dict-likes and sequences (traversed in insertion / index order)
    "dict(gen of items)": lambda n: dict((i, K(i)) for i in range(n)),
    "dict(zip(range, [listcomp]))": lambda n: dict(zip(range(n), [K(i) for i in range(n)])),
    "frozendict(gen of items)": lambda n: builtins.frozendict((i, K(i)) for i in range(n)),
    "tuple(gen)": lambda n: tuple(K(i) for i in range(n)),
    "list(gen)": lambda n: list(K(i) for i in range(n)),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=1_000_000)
    a = ap.parse_args()
    header(f"Full gc.collect() time after building a container of {a.n:,} GC-tracked elements",
           "Per row: build, collect once, then the median of 3 more full collections",
           f"(a few seconds per row). \"slow\" = over 3x the {BASELINE} row, which builds",
           "the same set but tracks it before its elements.")
    base = None
    for name, build in PATTERNS.items():
        print(f"  {name:34s}", end=" ", flush=True)
        if name.startswith("frozendict") and not hasattr(builtins, "frozendict"):
            print("  (no frozendict in this version)")
            continue
        gc.collect()
        obj = build(a.n)
        gc.collect()
        times = []
        for _ in range(3):
            t = time.perf_counter()
            gc.collect()
            times.append(time.perf_counter() - t)
        del obj
        t = statistics.median(times)
        if base is None:
            base, verdict = t, "baseline"
        elif t > 3 * base:
            verdict = f"slow ({t / base:.0f}x): elements scattered in memory"
        else:
            verdict = "ok"
        print(f"{t:6.2f}s  {verdict}", flush=True)


if __name__ == "__main__":
    main()
