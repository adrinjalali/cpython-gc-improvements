# Sets built from iterators make later full GCs ~10x slower (gh-152235)

[gh-152235](https://github.com/python/cpython/issues/152235) GC-tracks a set built from an
iterable only once it is full, so a half-built set can't be reached through
`gc.get_objects()`. With a generator, the set then sits behind its elements in the GC
list: the first full collection relinks them in hash order, and every later one walks
them scattered in memory, ~10x slower for 1M objects. Free-threaded builds are
unaffected. The change also stopped calling the `tp_alloc` of C subclasses of set.

Here: reproducers, five candidate fixes for main, backports of two (plus a `tp_alloc`
fix) to 3.15/3.14/3.13, and measurements, all via [pixi](https://pixi.sh).

```python
import gc, time

class K:
    pass

def pairs(n):
    return ((K(), i) for i in range(n))

s = set(pairs(1_000_000))
gc.collect()
t = time.perf_counter(); gc.collect(); print(f"{time.perf_counter() - t:.2f}s")
# 3.14.6: 0.12s   3.14.10: 1.50s   3.15.2: 1.44s
```

## The change

All merged 26 June 2026. A full `gc.collect()` after `set(gen)` of 1M objects (the 2nd
after the build), on source builds of the last ref without the change and the first with
it (`results/the-change.txt`):

| branch | gh-152235 PRs | without → with | full GC: without → with |
|---|---|---|---|
| main | gh-152237, gh-152273, gh-152290 | `55bc3126e0a` → `908f438e198` (gh-152237) | 0.12 s → 1.15 s |
| 3.15 | gh-152242, gh-152278, gh-152316 | 3.15.0b3 → 3.15.0b4 | 0.13 s → 1.15 s |
| 3.14 | gh-152243, gh-152279, gh-152312 | 3.14.6 → 3.14.7 | 0.12 s → 1.15 s |
| 3.13 | gh-152272, gh-152280, gh-152319 | 3.13.14 → 3.13.15 | 0.13 s → 1.28 s |

Every later release has it, and so does today's main (0.69 s: its collector has got
faster, but the set is still behind its elements).

The pixi environments are stock conda-forge builds, unpatched (`results/versions.txt`,
`results/pandas.txt`):

| environment | CPython | `set(gen)` tracked | full GC after `set(gen)` | with `(pd.Timestamp, int)`: literal genexpr / generator from a function |
|---|---|---|---|---|
| py310, py312 | 3.10.22, 3.12.16 | ahead of its elements | 0.12 s | |
| py31314 | 3.13.14 | ahead | 0.12 s | |
| py31318 | 3.13.18 | behind | 1.25 s | |
| py3146, pd3146 | 3.14.6 | ahead | 0.11 s | 0.17 s / 0.32 s |
| py31410, pd31410 | 3.14.10 | behind | 1.07 s | 1.50 s / 1.38 s |
| py315 | 3.15.2 | behind | 1.06 s | |
| ft3146, ft31410 | 3.14.6t, 3.14.10t | n/a (free-threaded: no GC list) | 0.09 s | |

(3.15+ compiles a literal `set(x for x in ...)` inline, so that one form is fast there;
generators made elsewhere, `map()` and `zip()` are not.)

## Running it

See the problem on the stock interpreters:

```sh
pixi run -e py31410 perf          # 3.14.10: set constructors vs a baseline (repro/gc_order_perf.py)
pixi run -e py3146 perf           # 3.14.6, before the change: all ok
pixi run -e py31410 other-types   # other containers and patterns (repro/other_types.py)
pixi run -e pd31410 pandas        # with pandas Timestamps
pixi run -e ft3146 race           # the free-threaded race gh-152235 fixed (also race-frozenset)
pixi run -e py3146 gil            # what a half-built set breaks with the GIL
bash tools/run-matrix.sh repro/gc_order_perf.py --check-order   # every environment and build
```

Each script first prints which interpreter it runs on, whether it carries a patch from
this repo, and whether `set(gen)` is tracked behind its elements. Each row then prints
as it is measured (a few seconds each), with a verdict against the `s.update(gen)` row,
which builds the same set but tracks it first:

```
$ pixi run -e py31410 perf
Full gc.collect() times after building a set of 1,000,000 (Key, int) tuples
  Python 3.14.10: conda-forge build, unpatched
  set(gen) is GC-tracked behind its elements (gh-152235's change)
  ...
  s=set(); s.update(gen)             1st  0.10s  2nd  0.10s  set ahead   baseline
  {x for x in gen}                   1st  0.10s  2nd  0.10s  set ahead   ok
  set(gen)                           1st  0.74s  2nd  1.07s  set behind  slow (10x)
  frozenset(gen)                     1st  0.71s  2nd  1.07s  set behind  slow (10x)
  ...
```

Try a fix: build CPython from source (linux-64, a few minutes) with a patch set, then run
the same scripts with it:

```sh
pixi run build-cpython v3.14.10 none                           # -> .scratch/build/v3.14.10/python
pixi run build-cpython v3.14.10 3.14/revive-in-address-order   # -> .scratch/build/v3.14.10-revive-in-address-order/python
.scratch/build/v3.14.10/python repro/other_types.py                           # slow rows
.scratch/build/v3.14.10-revive-in-address-order/python repro/other_types.py   # all ok
```

`build-cpython REF [PATCHSET] [MODE]`: REF is `main` (commit
`4497fe9889105b1abc6d633971e84ee9f78bd3b8`), a tag or a commit; PATCHSET is `none` or a
directory under `patches/` (`main/*` for main, `3.15|3.14|3.13/*` for v3.15.2, v3.14.10,
v3.13.18); MODE is release, debug, ft or ft-debug. Sources come from GitHub
(`CPYTHON_ARCHIVE` sets a mirror). To compare builds:

```sh
B=.scratch/build
pixi run -e py31410 python tools/compare-gc.py -r 3 --cpu 2 main=$B/main/python revive=$B/main-revive-in-address-order/python
pixi run -e py31410 python tools/count-instructions.py main=$B/main/python revive=$B/main-revive-in-address-order/python
```

Environments: py310 py312 py31314 py31318 py3146 py31410 py315, ft3146 ft31410
(free-threaded), pd3146 pd31410 (pandas), for linux-64 and osx-arm64.

## Why it happens

`_PyObject_GC_TRACK()` appends to the youngest generation, so objects sit in creation
order. In a full collection `move_unreachable()` meets each element before the set, with
`gc_refs == 0`, and moves it to `unreachable`; on reaching the set, `visit_reachable()`
moves them back in `set_traverse()` order, i.e. hash order. With the set first, they are
marked reachable in place and nothing moves.

2nd full collection, 1M elements (`results/other-types.txt`):

| pattern | 3.10 | 3.14.6 | 3.14.10 | 3.15.2 | main |
|---|---|---|---|---|---|
| `s = set(); s.update(gen)` (baseline) | 0.11 s | 0.11 s | 0.11 s | 0.11 s | 0.11 s |
| `set(gen)` | 0.12 s | 0.11 s | 1.06 s | 1.10 s | 0.69 s |
| `set([K() ...])`, list then dropped | 1.34 s | 1.18 s | 1.08 s | 1.13 s | 0.70 s |
| `frozenset(tuple(gen))` | 1.38 s | 1.07 s | 1.11 s | 1.08 s | 0.69 s |
| `dict`, `frozendict` (3.15+), `tuple`, `list` from a generator | 0.04-0.05 s | 0.04 s | 0.04 s | 0.04 s | 0.04 s |

- Only sets: dicts, frozendicts (also tracked late, gh-151722), lists and tuples traverse
  in insertion order, so relinking keeps creation order.
- A set that becomes the only owner of existing objects (`set([K() ...])`,
  `s = set(d); del d`) was always slow, 3.10 included. Not a regression, same problem;
  revive-in-address-order fixes it, source-hint for lists and dicts.
- main's collector is faster on scattered heaps than the release branches'; the
  baseline takes 0.11 s everywhere.

## Why gh-152235 is still needed

Reverting it (what 3.14.6 does) brings back two bugs:

- **Free-threaded:** the generator can find the half-built set via `gc.get_objects()`
  and hand it to another thread, which reads it while the lock-free fill resizes it. On
  3.14.6t that happens in 100/100 rounds, with inconsistent reads (a "frozen" set
  changing size) and sometimes a segfault; never on 3.14.10t (`results/ft-race.txt`).
- **GIL:** nothing is freed early (the filling C code holds a reference, so the set is a
  root), but a half-built frozenset found via `gc.get_objects()`/`get_referrers()` can
  cache a hash of a prefix and then isn't `==` to an equal frozenset. With a thread
  hashing `gc.get_objects()`, 76/77 such frozensets break on 3.10 and 76/76 on 3.14.6;
  none on 3.14.10 or 3.15.2 (`results/gil-halfbuilt.txt`). Rare, but wrong.

## Candidate fixes for main

`git format-patch` series in `patches/main/`, each with NEWS and tests:

| patch set | changes | idea | per-call cost, 5-element sets |
|---|---|---|---|
| `gc-api` | `pycore_gc.h`, `gc.c`, `gc_free_threading.c`, `setobject.c` | internal GC API: track an object at a position reserved before the fill (after the iterator, or a placeholder); the half-built set stays hidden | +1-2% tuple/`range`, +2-6% iterators |
| `swap` | `setobject.c` | track an empty set first, fill a private one, `set_swap_bodies()` | +1%, +8.5-25.5% iterators |
| `revive-in-address-order` | `gc.c` | sort each batch a collection moves back from `unreachable` by address | none |
| `non-moving-mark` | `gc.c` | mark reachable objects in place (flag + stack), sweep once | none |
| `source-hint` | gc-api + `setobject.c` | also track a set built from a large (>= 1024) list/tuple/dict/set right after it | about gc-api's |

Full GCs after building 1M elements, first / steady, seconds; median of 3 interleaved
pinned runs (`results/main-gc-compare.txt`; costs from `results/main-instructions.txt`):

| pattern | main | gc-api | swap | revive | non-moving | source-hint |
|---|---|---|---|---|---|---|
| `set(gen)` | 0.37 / 0.72 | 0.11 / 0.11 | 0.10 / 0.11 | 0.48 / 0.11 | 0.27 / 0.27 | 0.11 / 0.11 |
| `set([listcomp])`, list dropped | 0.37 / 0.70 | 0.37 / 0.69 | 0.37 / 0.70 | 0.48 / 0.11 | 0.27 / 0.27 | 0.11 / 0.11 |
| `s = set(d); del d` | 0.37 / 0.71 | 0.37 / 0.70 | 0.36 / 0.70 | 0.48 / 0.11 | 0.27 / 0.27 | 0.11 / 0.11 |
| `frozenset(tuple(gen))` | 0.37 / 0.70 | 0.37 / 0.72 | 0.36 / 0.71 | 0.47 / 0.11 | 0.27 / 0.27 | 0.36 / 0.71 |
| *relative to main:* | | | | | | |
| tree of 1M, full GC | 1.00 | 1.00 | 1.01 | 1.02 | 1.19 | 1.00 |
| the same, build (young GCs) | 1.00 | 0.99 | 0.99 | 1.02 | 1.09 | 1.00 |
| bottom-up tree, first / steady | 1.00 | 1.00 / 0.98 | 0.99 / 0.98 | 1.05 / 0.95 | 1.00 / 1.08 | 1.00 / 0.97 |
| 200k two-object cycles | 1.00 | 1.01 | 0.99 | 1.00 | 1.06 | 1.00 |
| allocation churn | 1.00 | 0.97 | 0.98 | 0.97 | 0.97 | 0.96 |

- **revive-in-address-order** fixes every pattern in steady state at no per-call cost;
  it pays a one-time sort (0.48 s vs 0.37 s) and 8 bytes per revived object, in the
  collector's core loop.
- **gc-api** and **swap** fix the regression with the fastest first GC; **source-hint**
  adds lists and dicts (not tuples: a tuple is created after its elements).
- **non-moving-mark** stalls at 0.27 s (the set is still behind its elements) and costs
  6-23% on well-ordered heaps.
- revive-in-address-order + gc-api combine both strengths.

Tests: each series' new tests fail on main and pass with it; GC suites pass on debug
builds (`GC_DEBUG` checks) and `-R 3:3`; `patchcheck` passes; the full suite fails only
where main does. Non-PGO noise: `dict_of_lists` (raw results) shows gc-api 30% faster
with no sets; `test_gdb` pretty-printing fails if the build dir name has non-letters.

## Backports

gh-152235 is on every branch, so `patches/3.15`, `patches/3.14` and `patches/3.13` carry
gc-api, revive-in-address-order and tp-alloc as `[3.x]` commits with main's message,
tests and NEWS. They add and remove the same lines as main, except 3.13 gc-api
(`set.union()` takes a tuple; no `heap_size` counter). swap and source-hint apply to
3.15 (with fuzz to 3.14) but are untested there; non-moving-mark doesn't apply.

2nd full GC after building 1M elements, source builds (`results/backports-gc.txt`):

| build | `set(gen)` | `set([K() ...])`, list dropped | `frozenset(tuple(gen))` |
|---|---|---|---|
| v3.15.2 / + gc-api / + revive | 1.13 / 0.12 / 0.13 s | 1.14 / 1.14 / 0.14 s | 1.15 / 1.11 / 0.14 s |
| v3.14.10 / + gc-api / + revive | 1.12 / 0.12 / 0.14 s | 1.12 / 1.13 / 0.14 s | 1.13 / 1.13 / 0.14 s |
| v3.13.18 / + gc-api / + revive | 1.36 / 0.13 / 0.15 s | 1.32 / 1.26 / 0.15 s | 1.36 / 1.31 / 0.15 s |

Tests (`results/backports-tests*.txt`), per branch and for `patches/main/tp-alloc`: new
tests fail without the patch, pass with it; set/GC/weakref/finalization suites (+
`test_capi.test_set`) pass on release and `-R 3:3` debug builds, `test_set`/`test_gc`/
`test_capi.test_set` on free-threaded ones; with gc-api, `ft_race.py` never sees a
half-built set and `test_set_gc_order.py`/`gil_halfbuilt.py` pass. Full suite: the five
main candidates only.

## Subclasses' `tp_alloc`

Since gh-152235 (every branch), `make_new_set()` calls `_PyType_AllocNoTrack()` instead
of `type->tp_alloc`, so a C subclass's own allocator isn't called while its `tp_free`
still is, and set's inherited `tp_alloc` slot returns untracked objects (`ext/csetsub.c`,
`pixi run -e build bash tools/run-ext.sh PYTHON`). `patches/*/tp-alloc` calls
`type->tp_alloc` again when it isn't `PyType_GenericAlloc` (untracked until full),
restores `PyType_GenericAlloc` as the slot, and tests it in `test_capi.test_set`. Custom
`tp_alloc` calls for 100 `CSet(gen)` / `CFrozen(gen)`: 0 / 0 on main, 3.15.2, 3.14.10
and 3.13.18; 100 / 100 with tp-alloc, default and free-threaded.

## Method

- One shared machine (load in each results file): x86-64 Rocky 8, AMD EPYC Genoa, 64
  cores, 188 GiB. Source builds: conda-forge GCC 15.3, `-O3`, no PGO/LTO; compare them
  with each other, not with release binaries.
- GC times on one pinned core, medians of 3 (interleaved runs for the main comparison
  and the change table).
  Per-call cost: `perf stat` instructions, `PYTHONHASHSEED=0`. Workload and per-call
  costs measured on main only; the backports change the same code.
- Free-threaded builds keep no GC list, so the scripts skip the order checks there.

## Layout

- `repro/`: `gc_order_perf.py` (slowdown + order check), `other_types.py`, `describe.py` (the header each script prints),
  `pandas_timestamps.py`, `ft_race.py`, `gil_halfbuilt.py`, `gc_bench.py`,
  `instr_loop.py`, `test_set_gc_order.py` (extra gc-api tests)
- `tools/`: `build-cpython.sh`, `compare-gc.py`, `count-instructions.py`,
  `run-matrix.sh`, `run-ext.sh`; `ext/`: C subclasses with their own `tp_alloc`
- `patches/main/*`: the candidates and tp-alloc; `patches/3.15|3.14|3.13/*`: backports
- `results/`: the raw numbers behind every table

Prepared with help from an AI assistant (Claude).
