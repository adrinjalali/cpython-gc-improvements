"""How long does a full gc.collect() take after building a big set, by build pattern?

No pandas needed: each element is a tuple (Key(i), i), which like
(pd.Timestamp(i), i) is GC-tracked and has a value-based (scrambling) hash.

    python repro/gc_order_perf.py [-n 1000000] [pattern ...]

For each pattern it prints:
  1st     the first full collection after building (moves the elements)
  2nd     the median of the next full collections (pays for the order the 1st left)
  order   with --check-order: is the set ahead of or behind its elements in the GC list
"""

import argparse
import gc
import statistics
import time

from describe import free_threaded, header


class Key:
    __slots__ = ("v",)  # instances are GC-tracked, like pd.Timestamp

    def __init__(self, v):
        self.v = v


def elems(n):
    return ((Key(i), i) for i in range(n))


BASELINE = "s=set(); s.update(gen)"

PATTERNS = {
    # the workaround, and the baseline: the set exists (and is tracked) first
    BASELINE: lambda n: (s := set(), s.update(elems(n)), s)[2],
    "{x for x in gen}": lambda n: {x for x in elems(n)},
    # the constructor paths gh-152235 changed (gh-152237, gh-152273, gh-152290)
    "set(gen)": lambda n: set(elems(n)),
    "frozenset(gen)": lambda n: frozenset(elems(n)),
    "set().union(gen)": lambda n: set().union(elems(n)),
    "set().symmetric_difference(gen)": lambda n: set().symmetric_difference(elems(n)),
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
    header(f"Full gc.collect() times after building a set of {a.n:,} (Key, int) tuples",
           "1st = first full collection after the build (it relinks the elements);",
           f"2nd = median of the next {a.repeats} (pays for the order the 1st left).",
           f"A few seconds per row. \"slow\" = 2nd over 3x the {BASELINE} row.")
    patterns = sorted(a.patterns, key=lambda p: p != BASELINE)  # baseline first
    base = None
    for p in patterns:
        print(f"  {p:34s}", end=" ", flush=True)
        order = ""
        if a.check_order and not free_threaded():  # no GC list order there
            gc.disable()
            try:
                s = PATTERNS[p](1000)
                order = "  set ahead " if set_first(s) else "  set behind"
            finally:
                gc.enable()
            del s
        first, second = run(p, a.n, a.repeats)
        if p == BASELINE:
            base, verdict = second, "baseline"
        elif base is not None and second > 3 * base:
            verdict = f"slow ({second / base:.0f}x)"
        else:
            verdict = "ok" if base is not None else ""
        print(f"1st {first:5.2f}s  2nd {second:5.2f}s{order}  {verdict}", flush=True)


if __name__ == "__main__":
    main()
