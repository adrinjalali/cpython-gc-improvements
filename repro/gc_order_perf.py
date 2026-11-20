"""How long does a full gc.collect() take after building a big set, by build pattern?

No pandas needed: each element is a tuple (Key(i), i), which like
(pd.Timestamp(i), i) is GC-tracked and has a value-based (scrambling) hash.

    python repro/gc_order_perf.py [-n 1000000] [pattern ...]

For each pattern it prints:
  set_first  whether the set sits before its elements in the GC list
  1st        the first full collection after building (moves the elements)
  2nd        the median of the next full collections (pays for the order the 1st left)
"""

import argparse
import gc
import statistics
import sys
import time


class Key:
    __slots__ = ("v",)  # instances are GC-tracked, like pd.Timestamp

    def __init__(self, v):
        self.v = v


def elems(n):
    return ((Key(i), i) for i in range(n))


PATTERNS = {
    # the constructor paths gh-152235 changed (gh-152237, gh-152273, gh-152290)
    "set(gen)": lambda n: set(elems(n)),
    "frozenset(gen)": lambda n: frozenset(elems(n)),
    "set().union(gen)": lambda n: set().union(elems(n)),
    "set().symmetric_difference(gen)": lambda n: set().symmetric_difference(elems(n)),
    # the workaround: the set exists (and is tracked) before the elements
    "s=set(); s.update(gen)": lambda n: (s := set(), s.update(elems(n)), s)[2],
    "{x for x in gen}": lambda n: {x for x in elems(n)},
}


def set_first(s):
    """Is the set before all its elements in GC list order?"""
    # get_objects(generation=g) lists g's objects oldest-first; generations are
    # concatenated oldest generation first, matching a full collection's scan.
    order = {}
    i = 0
    for gen in (2, 1, 0):
        for o in gc.get_objects(generation=gen):
            order[id(o)] = i
            i += 1
    return order[id(s)] < min(order[id(e)] for e in s)


def run(pattern, n, repeats):
    gc.collect()
    s = PATTERNS[pattern](n)
    t = time.perf_counter()
    gc.collect()
    first = time.perf_counter() - t
    later = []
    for _ in range(repeats):
        t = time.perf_counter()
        gc.collect()
        later.append(time.perf_counter() - t)
    return first, statistics.median(later)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=1_000_000)
    ap.add_argument("-r", "--repeats", type=int, default=3)
    ap.add_argument("--check-order", action="store_true",
                    help="also check whether the set is ahead of its elements (n=1000)")
    ap.add_argument("patterns", nargs="*", default=list(PATTERNS))
    a = ap.parse_args()
    print(f"# {sys.version.split()[0]} n={a.n:,}")
    for p in a.patterns:
        order = ""
        if a.check_order:
            gc.disable()
            try:
                s = PATTERNS[p](1000)
                order = "set_first" if set_first(s) else "ELEMENTS_FIRST"
            finally:
                gc.enable()
            del s
        first, second = run(p, a.n, a.repeats)
        print(f"{p:34s} 1st {first:6.2f}s  2nd {second:6.2f}s  {order}", flush=True)


if __name__ == "__main__":
    main()
