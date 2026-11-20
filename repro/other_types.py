"""Which containers and build patterns make later full collections slow?

    python repro/other_types.py [-n 1000000]

Same measurement as gc_order_perf.py (time of the 2nd full gc.collect() after building),
for other container types and for sets built from existing objects. Elements are
GC-tracked: (K(), i) tuples for set-likes, K() values for dict-likes.
"""

import argparse
import builtins
import gc
import statistics
import sys
import time


class K:
    __slots__ = ("v",)

    def __init__(self, v):
        self.v = v


def pairs(n):
    return ((K(i), i) for i in range(n))


PATTERNS = {
    # set-likes (traversed in hash order)
    "set(gen)": lambda n: set(pairs(n)),
    "set([listcomp]) (list dropped)": lambda n: set([(K(i), i) for i in range(n)]),
    "frozenset(tuple(gen))": lambda n: frozenset(tuple(pairs(n))),
    "s.update(gen)": lambda n: (s := set(), s.update(pairs(n)), s)[2],
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
    print(f"# {sys.version.split()[0]}{' free-threaded' if not getattr(sys, '_is_gil_enabled', lambda: True)() else ''}")
    for name, build in PATTERNS.items():
        if name.startswith("frozendict") and not hasattr(builtins, "frozendict"):
            print(f"{name:34s} (no frozendict)")
            continue
        gc.collect()
        obj = build(a.n)
        gc.collect()
        times = []
        for _ in range(3):
            t = time.perf_counter()
            gc.collect()
            times.append(time.perf_counter() - t)
        print(f"{name:34s} {statistics.median(times):6.2f}s", flush=True)
        del obj


if __name__ == "__main__":
    main()
