"""Tests for the gc-api patch sets (patches/*/gc-api), runnable with plain
`python -m unittest` (no pytest needed).

Two properties, for every constructor path gh-152235 changed:
  * order:    the finished set is ahead of the elements its fill created in the GC
              list
  * hidden:   the half-built set can't be found via gc.get_objects()/get_referrers()
Plus the patch's edge cases: errors mid-fill, gc.freeze() mid-fill, subclasses.

On the default (GIL) build:
  before gh-152235 (3.13.14, 3.14.6):      order passes, hidden fails
  with it (3.13.15+, 3.14.7+, 3.15, main):  order fails, hidden passes
  with a gc-api patch set:                  both pass
"""

import gc
import sys
import unittest


class Obj:
    pass


class Val:
    """Hashable by value, so intersection keeps the iterator's (new) objects."""

    __slots__ = ("v", "__weakref__")

    def __init__(self, v):
        self.v = v

    def __hash__(self):
        return hash(self.v)

    def __eq__(self, other):
        return isinstance(other, Val) and self.v == other.v


class SetSub(set):
    pass


class FrozenSub(frozenset):
    pass


BASE = {Val(i) for i in range(100)}  # built (and GC-tracked) before any test

class Iterable:
    """Not an iterator: the patch uses a placeholder rather than the iterable."""

    def __init__(self, it):
        self.it = it

    def __iter__(self):
        return iter(self.it)


BUILDERS = {
    "set": lambda it: set(it),
    "set(non-iterator iterable)": lambda it: set(Iterable(it)),
    "frozenset": lambda it: frozenset(it),
    "union": lambda it: set().union(it),
    "union_multi": lambda it: set().union([], it),
    "symmetric_difference": lambda it: set().symmetric_difference(it),
    "intersection": lambda it: BASE.intersection(it),
    "frozenset.union": lambda it: frozenset().union(it),
    "set_subclass_union": lambda it: SetSub().union(it),
    "frozenset_subclass": lambda it: FrozenSub(it),
}

FREE_THREADED = not getattr(sys, "_is_gil_enabled", lambda: True)()


def elems(n=100):
    return (Val(i) for i in range(n))


def gc_order():
    order = {}
    for gen in (2, 1, 0):  # oldest first: the order a full collection scans
        for o in gc.get_objects(generation=gen):
            order[id(o)] = len(order)
    return order


class Order(unittest.TestCase):
    @unittest.skipIf(FREE_THREADED, "free-threaded GC has no list order")
    def test_set_is_gc_tracked_before_its_elements(self):
        for name, build in BUILDERS.items():
            with self.subTest(name):
                gc.disable()
                try:
                    s = build(elems())
                    self.assertTrue(gc.is_tracked(s))
                    self.assertEqual(len(s), 100)
                    order = gc_order()
                    self.assertLess(order[id(s)], min(order[id(e)] for e in s))
                finally:
                    gc.enable()

    @unittest.skipIf(FREE_THREADED, "free-threaded GC has no list order")
    def test_order_survives_collections_during_fill(self):
        # Young collections during the fill promote the placeholder (and the
        # elements) to older generations; the set must still end up ahead.
        def gen():
            for i in range(20_000):
                if i % 3000 == 0:
                    gc.collect(i // 3000 % 3)
                yield Val(i)

        for name, build in BUILDERS.items():
            if name == "intersection":
                continue
            with self.subTest(name):
                s = build(gen())
                order = gc_order()
                self.assertLess(order[id(s)], min(order[id(e)] for e in s))


class Hidden(unittest.TestCase):
    def test_half_built_set_is_not_reachable(self):
        for name, build in BUILDERS.items():
            with self.subTest(name):
                first = Val(0)
                found = []

                def gen():
                    yield first
                    # identity, not ==: other live sets hold an equal Val(0)
                    found.extend(o for o in gc.get_objects()
                                 if isinstance(o, (set, frozenset))
                                 and any(x is first for x in o))
                    found.extend(o for o in gc.get_referrers(first)
                                 if isinstance(o, (set, frozenset)) and o is not BASE)
                    yield from elems()

                s = build(gen())
                self.assertIn(first, s)
                self.assertEqual(found, [])


class EdgeCases(unittest.TestCase):
    def test_error_mid_fill(self):
        def gen():
            yield from elems(10)
            raise ZeroDivisionError

        for name, build in BUILDERS.items():
            with self.subTest(name):
                before = len(gc.get_objects())
                for _ in range(100):
                    with self.assertRaises(ZeroDivisionError):
                        build(gen())
                gc.collect()
                self.assertLess(len(gc.get_objects()) - before, 50)

    @unittest.skipIf(FREE_THREADED, "free-threaded GC has no list order")
    def test_order_with_frozen_objects(self):
        # Once anything is frozen, the patch uses a placeholder, never the iterator.
        junk = [Obj() for _ in range(10)]
        gc.freeze()
        try:
            for name, build in BUILDERS.items():
                with self.subTest(name):
                    s = build(elems())
                    order = gc_order()  # generations 0-2 only, not permanent
                    self.assertIn(id(s), order)
                    self.assertLess(order[id(s)], min(order[id(e)] for e in s))
        finally:
            gc.unfreeze()
        del junk

    def test_freeze_during_fill_does_not_freeze_the_set(self):
        # The iterator is frozen mid-fill; the set must not follow it into the
        # permanent generation (it would never be collected).
        def gen():
            yield from elems(10)
            gc.freeze()
            yield from elems(10)

        try:
            s = set(gen())
            self.assertTrue(gc.is_tracked(s))
            self.assertTrue(any(o is s for o in gc.get_objects()))
        finally:
            gc.unfreeze()

    def test_build_in_finalizer_from_unreachable_iterator(self):
        # __del__ of a garbage cycle consumes an iterator that is itself part of
        # the garbage being collected (in the collector's unreachable list).
        results = []

        class Holder:
            def __init__(self):
                self.it = (Val(i) for i in range(50))
                self.me = self

            def __del__(self):
                results.append(set(self.it))

        for _ in range(20):
            Holder()
        gc.collect()
        gc.collect()
        self.assertEqual(len(results), 20)
        for r in results:
            self.assertEqual(len(r), 50)
            self.assertTrue(any(o is r for o in gc.get_objects()))
        del results[:]
        gc.collect()

    def test_freeze_mid_fill(self):
        # gc.freeze() during the fill moves the placeholder into the permanent
        # generation; the set goes with it, as a set tracked early always did.
        def gen():
            yield from elems(10)
            gc.freeze()
            yield from elems(10)

        try:
            s = set(gen())
            self.assertTrue(gc.is_tracked(s))
            self.assertEqual(len(s), 10)
        finally:
            gc.unfreeze()
        gc.collect()

    def test_cycle_through_result_is_collected(self):
        import weakref

        class Node:
            pass

        def gen():
            for _ in range(10):
                yield Node()

        for name, build in BUILDERS.items():
            if name == "intersection":
                continue
            with self.subTest(name):
                s = build(gen())
                n = next(iter(s))
                n.back = s  # cycle: set -> node -> set
                w = weakref.ref(n)
                del s, n
                gc.collect()
                self.assertIsNone(w())

    def test_iterables_that_skip_the_placeholder(self):
        lst = [Val(i) for i in range(10)]
        for it in (lst, tuple(lst), set(lst), frozenset(lst), dict.fromkeys(lst), "abc"):
            with self.subTest(type(it).__name__):
                self.assertEqual(len(set(it)), len(it))
                self.assertTrue(gc.is_tracked(set(it)))


if __name__ == "__main__":
    print(sys.version)
    unittest.main(verbosity=1)
