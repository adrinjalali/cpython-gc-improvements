"""What can a half-built set break in the default (GIL) build?

Before gh-152235 (3.13.14, 3.14.6 and older), code that runs while set(it) /
frozenset(it) fills the new set -- the iterable, or element __hash__/__eq__ -- can find the set
with gc.get_objects() or gc.get_referrers(). With the GIL there is no data race, so
the question is what else can go wrong. Each check prints OK or BROKEN.

  1. frozenset hashed while half-built: frozenset caches its hash, so the finished
     frozenset keeps the hash of a prefix of its elements. It then compares equal to
     an identical frozenset but hashes differently, so dict/set lookups miss.
  2. gc.collect() at every step of the fill, from the iterable and from __hash__ /
     __eq__, with elements in reference cycles through the half-built set: can the
     GC free the set or an element too early? (It shouldn't: the C code filling the
     set holds a reference the GC can't see, so the set is a root.)
  3. The half-built *mutable* set grabbed and mutated during the fill: same as
     s = set(); s.update(it) where `it` mutates s, which has always been allowed.
  4. Like 1, but nothing in the set-building code touches gc: another thread (say a
     memory profiler) walks gc.get_objects() and hashes what it finds, and the GIL
     hands it control in the middle of a frozenset(generator) fill.

Run it on a --with-pydebug build too, so the GC's own consistency asserts are on.
"""

import gc
import sys
import weakref


def find_halfbuilt(kind, marker):
    for o in gc.get_objects():
        if type(o) is kind and marker in o:
            return o
    return None


def check_frozenset_hash():
    marker = object()
    leaked = []

    def gen():
        yield marker
        fs = find_halfbuilt(frozenset, marker)
        if fs is not None:
            leaked.append(len(fs))
            hash(fs)  # caches the hash of the one-element prefix
        yield from range(1000)

    fs = frozenset(gen())
    same = frozenset(list(fs))  # a fresh, equal frozenset
    ok = fs == same and hash(fs) == hash(same) and same in {fs}
    detail = (f"half-built frozenset {'seen at len ' + str(leaked[0]) if leaked else 'not reachable'}; "
              f"equal={fs == same} same_hash={hash(fs) == hash(same)} lookup_hits={same in {fs}}")
    return ok, detail


class Elem:
    """Element whose __hash__/__eq__ run the GC and whose `back` can close a cycle."""

    __slots__ = ("v", "back", "__weakref__")

    def __init__(self, v):
        self.v = v
        self.back = None

    def __hash__(self):
        if self.v % 7 == 0:
            gc.collect()
        return hash(self.v % 5000)  # collisions, so __eq__ runs during the fill

    def __eq__(self, other):
        if self.v % 11 == 0:
            gc.collect(0)
        return isinstance(other, Elem) and self.v == other.v


def check_gc_during_fill(kind):
    marker = Elem(-1)
    grabbed = []
    refs = []

    def gen(n):
        yield marker
        for i in range(n):
            e = Elem(i)
            refs.append(weakref.ref(e))
            if i == 10:
                s = find_halfbuilt(kind, marker)
                if s is not None:
                    grabbed.append(s)
                    e.back = s  # cycle: set -> e -> set
            if i % 50 == 0:
                gc.collect()
            yield e

    s = kind(gen(3000))
    gc.collect()
    alive = sum(r() is not None for r in refs)
    ok = len(s) == 3001 and alive == 3000 and all(isinstance(x, Elem) for x in s)
    cycle = bool(grabbed) and grabbed[0] is s
    # Drop everything: the cycle (if any) must be collectable.
    w = weakref.ref(marker)
    del s, marker, grabbed
    gc.collect()
    freed = w() is None and sum(r() is not None for r in refs) == 0
    return ok and freed, (f"len ok={ok} (alive {alive}/3000); cycle through half-built set: {cycle}; "
                          f"all freed afterwards={freed}")


def check_mutate_halfbuilt():
    marker = object()
    seen = []

    def gen():
        yield marker
        s = find_halfbuilt(set, marker)
        if s is not None:
            seen.append(True)
            s.clear()          # wipe what the fill has done so far
            s.update(range(-100, 0))
        yield from range(100)

    s = set(gen())
    want = set(range(100)) | (set(range(-100, 0)) if seen else {marker})
    return s == want, f"half-built set {'mutated during fill' if seen else 'not reachable'}; result consistent={s == want}"


def check_other_thread_hashes():
    import threading
    import time

    stop = threading.Event()

    def walker():
        while not stop.is_set():
            for o in gc.get_objects():
                if type(o) is frozenset:
                    hash(o)
            time.sleep(0.001)

    t = threading.Thread(target=walker, daemon=True)
    t.start()
    broken = total = 0
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        fs = frozenset(i * 7919 for i in range(200_000))
        total += 1
        if fs != frozenset(list(fs)):
            broken += 1
    stop.set()
    t.join()
    return broken == 0, f"{broken}/{total} frozensets built while another thread hashed gc objects are != an equal frozenset"


def main():
    print(f"# {sys.version.split()[0]} {'debug build' if hasattr(sys, 'gettotalrefcount') else ''}")
    checks = [
        ("1 frozenset hashed while half-built", check_frozenset_hash),
        ("2 gc.collect() during set fill", lambda: check_gc_during_fill(set)),
        ("2 gc.collect() during frozenset fill", lambda: check_gc_during_fill(frozenset)),
        ("3 half-built set mutated", check_mutate_halfbuilt),
        ("4 another thread hashes gc.get_objects()", check_other_thread_hashes),
    ]
    for name, f in checks:
        ok, detail = f()
        print(f"{'OK    ' if ok else 'BROKEN'} {name}: {detail}", flush=True)


if __name__ == "__main__":
    main()
