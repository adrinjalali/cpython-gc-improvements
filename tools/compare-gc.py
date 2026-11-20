#!/usr/bin/env python3
"""Run repro/gc_bench.py for every interpreter and scenario; print median tables.

    python tools/compare-gc.py [-r REPEATS] [--cpu N] [--json OUT] LABEL=PYTHON ...

Runs are interleaved (scenario, repeat, interpreter), so slow drift on the machine hits
all interpreters alike.  Each run is a fresh process, pinned to CPU N with taskset if
--cpu is given.  The first LABEL is the baseline for the ratios.
"""

import argparse
import collections
import json
import pathlib
import shutil
import statistics
import subprocess

HERE = pathlib.Path(__file__).resolve().parent.parent
BENCH = HERE / "repro" / "gc_bench.py"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-r", "--repeats", type=int, default=3)
    ap.add_argument("--cpu", help="pin each run to this CPU (Linux taskset)")
    ap.add_argument("--json")
    ap.add_argument("--scenarios", help="comma-separated (default: all)")
    ap.add_argument("variants", nargs="+", metavar="LABEL=PYTHON")
    a = ap.parse_args()
    variants = dict(v.split("=", 1) for v in a.variants)
    prefix = []
    if a.cpu is not None:
        if not shutil.which("taskset"):
            ap.error("--cpu needs taskset")
        prefix = ["taskset", "-c", a.cpu]
    first_py = next(iter(variants.values()))
    scenarios = (a.scenarios.split(",") if a.scenarios else
                 subprocess.check_output([first_py, BENCH, "--list"], text=True).split())

    results = collections.defaultdict(lambda: collections.defaultdict(list))
    for scenario in scenarios:
        for _ in range(a.repeats):
            for label, py in variants.items():
                out = subprocess.run(prefix + [py, BENCH, scenario],
                                     capture_output=True, text=True)
                if out.returncode != 0:
                    print(f"{label} {scenario} failed:\n{out.stderr[-2000:]}")
                    continue
                for key, value in json.loads(out.stdout).items():
                    if key != "scenario":
                        results[(scenario, key)][label].append(value)
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(
            {f"{s}.{k}": dict(v) for (s, k), v in results.items()}, indent=1))

    labels = list(variants)
    base = labels[0]
    print(f"Median of {a.repeats} runs, seconds; in brackets: vs {base}.")
    print()
    print("| scenario | metric | " + " | ".join(labels) + " |")
    print("|---|---|" + "---|" * len(labels))
    for (scenario, key), per in results.items():
        med = {label: statistics.median(per[label]) for label in labels if per.get(label)}
        cells = []
        for label in labels:
            if label not in med:
                cells.append("-")
            elif label == base:
                cells.append(f"{med[label]:.3f}")
            else:
                cells.append(f"{med[label]:.3f} ({med[label] / med[base]:.2f}x)")
        print(f"| {scenario} | {key} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()
