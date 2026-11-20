#!/usr/bin/env python3
"""Instructions per set-constructor call, per interpreter (Linux perf, user space).

    python tools/count-instructions.py [-r REPEATS] LABEL=PYTHON ...

Instruction counts don't depend on machine load the way timings do.  PYTHONHASHSEED is
pinned so runs repeat exactly.  Each case runs repro/instr_loop.py; the empty loop
("base") is subtracted.  The first LABEL is the baseline.
"""

import argparse
import collections
import os
import pathlib
import statistics
import subprocess

HERE = pathlib.Path(__file__).resolve().parent.parent
LOOP = HERE / "repro" / "instr_loop.py"
N = 2_000_000  # calls per run, as in instr_loop.py


def count(py, case):
    env = dict(os.environ, PYTHONHASHSEED="0")
    out = subprocess.run(["perf", "stat", "-x,", "-e", "instructions:u", py, LOOP, case],
                         capture_output=True, text=True, env=env, check=True)
    for line in out.stderr.splitlines():
        if "instructions" in line:
            return int(line.split(",")[0])
    raise RuntimeError(out.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-r", "--repeats", type=int, default=3)
    ap.add_argument("variants", nargs="+", metavar="LABEL=PYTHON")
    a = ap.parse_args()
    variants = dict(v.split("=", 1) for v in a.variants)
    first_py = next(iter(variants.values()))
    cases = subprocess.check_output(
        [first_py, "-c", f"import runpy; m = runpy.run_path({str(LOOP)!r}, "
         "run_name='x'); print(chr(10).join(m['CASES']))"], text=True).splitlines()
    d = collections.defaultdict(lambda: collections.defaultdict(list))
    for _ in range(a.repeats):
        for case in cases:
            for label, py in variants.items():
                d[case][label].append(count(py, case))
    labels = list(variants)
    base = labels[0]
    print(f"Instructions per call (median of {a.repeats}, PYTHONHASHSEED=0); "
          f"other columns vs {base}.")
    print()
    print("| call | " + " | ".join(labels) + " |")
    print("|---|" + "---|" * len(labels))
    for case in cases:
        if case == "base":
            continue
        per = {label: (statistics.median(d[case][label])
                       - statistics.median(d["base"][label])) / N for label in labels}
        u = per[base]
        cells = [f"{u:.0f}"] + [f"{per[label] - u:+.0f} ({100 * (per[label] / u - 1):+.1f}%)"
                                for label in labels[1:]]
        print(f"| `{case}` | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()
