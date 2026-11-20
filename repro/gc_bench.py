"""GC benchmarks for comparing collector and set-construction variants.

    python repro/gc_bench.py SCENARIO     # prints one JSON line
    python repro/gc_bench.py --list

Each scenario builds a heap, then times full collections: "first" is the first
gc.collect() after building, "steady" the median of the next three.  "build" is
the time to build the heap with automatic collection on (where it matters), and
"run" the whole timed loop for scenarios that measure throughput.
"""

import gc
import json
import statistics
import sys
import time

N = 1_000_000


class K:
    __slots__ = ("v",)

    def __init__(self, v):
        self.v = v


class Node:
    __slots__ = ("children",)

    def __init__(self, children=()):
        self.children = list(children)


def pairs(n):
    return ((K(i), i) for i in range(n))


def full_collections(keep):
    t = time.perf_counter()
    gc.collect()
    first = time.perf_counter() - t
    steady = []
    for _ in range(3):
        t = time.perf_counter()
        gc.collect()
        steady.append(time.perf_counter() - t)
    return {"first": first, "steady": statistics.median(steady)}


def timed_build(fn):
    gc.collect()
    t = time.perf_counter()
    obj = fn()
    return obj, time.perf_counter() - t


# -- set patterns ---------------------------------------------------------------

def set_from_generator():
    s, build = timed_build(lambda: set(pairs(N)))
    return {"build": build, **full_collections(s)}


def set_from_dropped_list():
    s, build = timed_build(lambda: set([(K(i), i) for i in range(N)]))
    return {"build": build, **full_collections(s)}


def set_from_deleted_dict():
    def make():
        d = {(K(i), i): None for i in range(N)}
        s = set(d)
        del d
        return s
    s, build = timed_build(make)
    return {"build": build, **full_collections(s)}


def frozenset_from_tuple():
    s, build = timed_build(lambda: frozenset(tuple(pairs(N))))
    return {"build": build, **full_collections(s)}


# -- general GC workloads -------------------------------------------------------

def tree_top_down():
    # Parents are created before their children: the common, well-ordered case.
    def make():
        root = Node()
        level = [root]
        count = 1
        while count < N:
            nxt = []
            for parent in level:
                for _ in range(4):
                    child = Node()
                    parent.children.append(child)
                    nxt.append(child)
                count += 4
            level = nxt
        return root
    root, build = timed_build(make)
    return {"build": build, **full_collections(root)}


def tree_bottom_up():
    # Children are created before their parents: the classic collector moves
    # them on the first collection.
    def make():
        level = [Node() for _ in range(N // 2)]
        while len(level) > 1:
            level = [Node(level[i:i + 4]) for i in range(0, len(level), 4)]
        return level[0]
    root, build = timed_build(make)
    return {"build": build, **full_collections(root)}


def dict_of_lists():
    def make():
        return {i: [K(j) for j in range(10)] for i in range(N // 10)}
    d, build = timed_build(make)
    return {"build": build, **full_collections(d)}


def cyclic_garbage():
    # Throughput of collecting garbage: 200k two-object cycles, five times.
    # Automatic collection is off while they are made, so they are all still
    # there when gc.collect() is timed.
    times = []
    for _ in range(5):
        gc.collect()
        gc.disable()
        for _ in range(200_000):
            a, b = Node(), Node()
            a.children.append(b)
            b.children.append(a)
        del a, b
        t = time.perf_counter()
        gc.collect()
        times.append(time.perf_counter() - t)
        gc.enable()
    return {"collect": statistics.median(times)}


def young_churn():
    # Allocation-heavy loop with automatic collection: mostly young collections.
    gc.collect()
    window = [None] * 1000
    t = time.perf_counter()
    for i in range(3_000_000):
        window[i % 1000] = [K(i), {"k": i}]
    return {"run": time.perf_counter() - t}


SCENARIOS = {f.__name__: f for f in (
    set_from_generator, set_from_dropped_list, set_from_deleted_dict,
    frozenset_from_tuple, tree_top_down, tree_bottom_up, dict_of_lists,
    cyclic_garbage, young_churn)}


def main():
    if sys.argv[1:] == ["--list"]:
        print("\n".join(SCENARIOS))
        return
    name = sys.argv[1]
    print(json.dumps({"scenario": name, **SCENARIOS[name]()}))


if __name__ == "__main__":
    main()
