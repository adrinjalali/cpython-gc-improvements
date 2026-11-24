"""The same slowdown with pandas Timestamps.

    python repro/pandas_timestamps.py

Times one full collection after building a set of 1M (pd.Timestamp, int) tuples, twice:
from a literal generator expression, and from a generator made by a function.
3.15+ compiles a literal set(genexpr) into an inline loop, so only the second form
shows the slowdown there; 3.13.15+ and 3.14.7+ show it for both.
"""
import gc
import time

import pandas as pd


def timed_full_collection():
    gc.collect()
    t = time.perf_counter()
    gc.collect()
    return time.perf_counter() - t


def pairs(n):
    return ((pd.Timestamp(i), i) for i in range(n))


from describe import header

header("Full gc.collect() time after building a set of 1M (pd.Timestamp, int) tuples",
       f"pandas {pd.__version__}; the 2nd full collection after the build, about 10 s in all.",
       "Before gh-152235 both take ~0.2-0.3 s; with it, ~1.5 s (only the second on 3.15+).")
print(f"  {'literal set(genexpr)':32s}", end=" ", flush=True)
s = set((pd.Timestamp(i), i) for i in range(1_000_000))
print(f"{timed_full_collection():.2f}s", flush=True)
del s
print(f"  {'set(generator from a function)':32s}", end=" ", flush=True)
s = set(pairs(1_000_000))
print(f"{timed_full_collection():.2f}s", flush=True)
