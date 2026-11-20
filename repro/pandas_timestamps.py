"""The slowdown with pandas Timestamps, as first seen.

    python repro/pandas_timestamps.py

Times one full collection after building a set of 1M (pd.Timestamp, int) tuples, twice:
from a literal generator expression, and from a generator made by a function.
3.15+ compiles a literal set(genexpr) into an inline loop, so only the second form
shows the slowdown there; 3.13.15+ and 3.14.7+ show it for both.
"""
import gc
import sys
import time

import pandas as pd


def timed_full_collection():
    gc.collect()
    t = time.perf_counter()
    gc.collect()
    return time.perf_counter() - t


def pairs(n):
    return ((pd.Timestamp(i), i) for i in range(n))


s = set((pd.Timestamp(i), i) for i in range(1_000_000))
literal = timed_full_collection()
del s
s = set(pairs(1_000_000))
from_function = timed_full_collection()
print(f"{sys.version.split()[0]} pandas {pd.__version__}: "
      f"literal set(genexpr) {literal:.2f}s, set(generator from a function) "
      f"{from_function:.2f}s")
