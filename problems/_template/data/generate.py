"""Synthetic dataset generator for <problem-id>.

Interviewer-only: this script is never provisioned into a candidate workspace;
only its output is. Must be deterministic for a given seed.

Usage: python generate.py [--out DIR] [--seed N]
"""

import argparse
from pathlib import Path

import numpy as np

SEED = 20260901  # fixed: same seed -> same dataset for every candidate


def generate(out_dir: Path, seed: int = SEED) -> None:
    rng = np.random.default_rng(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    raise NotImplementedError("write generator; document every column in data/README.md")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "out")
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    generate(args.out, args.seed)
