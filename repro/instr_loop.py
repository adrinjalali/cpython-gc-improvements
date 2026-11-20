"""One constructor call, N times, for counting instructions (tools/count-instructions.sh).

    python repro/instr_loop.py CASE
"""
import sys

t = (1, 2, 3, 4, 5)
s0 = {1, 2, 3}
d = dict.fromkeys(t)
N = 2_000_000


def gen(it):
    # A generator object made elsewhere: 3.15+ compiles a literal set(genexpr)
    # into an inline loop, so that row doesn't reach the set constructor there.
    return (x for x in it)


class UserIterable:
    def __iter__(self):
        return iter(t)


CASES = {
    "base": lambda: None,  # the loop itself, subtracted from the others
    "set(tuple)": lambda: set(t),
    "set(range(5))": lambda: set(range(5)),
    "set(genexpr)": lambda: set(x for x in t),
    "frozenset(genexpr)": lambda: frozenset(x for x in t),
    "set(gen(t))": lambda: set(gen(t)),
    "frozenset(gen(t))": lambda: frozenset(gen(t)),
    "set(map(int, t))": lambda: set(map(int, t)),
    "set(d.items())": lambda: set(d.items()),
    "set(UserIterable())": lambda: set(UserIterable()),
    "s.union(genexpr)": lambda: s0.union(x for x in t),
    "s.intersection(iter(t))": lambda: s0.intersection(iter(t)),
    "s.symmetric_difference(map)": lambda: s0.symmetric_difference(map(int, t)),
}

if __name__ == "__main__":
    f = CASES[sys.argv[1]]
    for _ in range(N):
        f()
