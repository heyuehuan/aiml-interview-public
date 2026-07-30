"""Synthetic transaction log generator for ml-txn-anomaly-001.

Interviewer-only. Deterministic for a given seed.

Planted pitfalls (documented in rubric.md):
  1. `review_outcome` — post-review column, near-perfect leakage for the label.
  2. ~1.5% exact duplicate rows (double-posted transactions).
  3. `amount` mixes currencies; `currency` column must be used to normalize.
  4. Labels exist only for previously-reviewed rows; the rest are NaN
     (candidates must notice this is not a fully-labeled dataset).
  5. Anomaly rate drifts upward in the final month (time-based split matters).

Usage: python generate.py [--out DIR] [--seed N]
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20260901  # fixed: same seed -> same dataset for every candidate
N_ROWS = 400_000
START = "2025-11-01"
DAYS = 181  # ~6 months

CURRENCIES = ["USD", "EUR", "GBP"]
FX_TO_USD = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27}
CHANNELS = ["card", "wire", "ach", "atm", "p2p"]
CATEGORY_POOL = [101, 102, 103, 104, 105, 106, 107, 108, 109, 110]  # opaque category codes
ELEVATED_CATEGORIES = {103, 106, 108}  # categories with a historically higher anomaly rate


def generate(out_dir: Path, seed: int = SEED) -> None:
    rng = np.random.default_rng(seed)
    out_dir.mkdir(parents=True, exist_ok=True)

    day = rng.integers(0, DAYS, N_ROWS)
    ts = pd.to_datetime(START) + pd.to_timedelta(
        day * 86400 + rng.integers(0, 86400, N_ROWS), unit="s"
    )

    n_customers = 12_000
    customer = rng.integers(0, n_customers, N_ROWS)
    channel = rng.choice(CHANNELS, N_ROWS, p=[0.55, 0.08, 0.2, 0.1, 0.07])
    category = rng.choice(CATEGORY_POOL, N_ROWS)
    currency = rng.choice(CURRENCIES, N_ROWS, p=[0.7, 0.2, 0.1])
    country = rng.choice(["US", "GB", "DE", "FR", "MX", "CA", "AU"], N_ROWS,
                         p=[0.6, 0.12, 0.08, 0.07, 0.06, 0.04, 0.03])
    hour = ts.hour.to_numpy()

    # Log-normal amounts in native currency.
    amount = np.round(np.exp(rng.normal(3.6, 1.3, N_ROWS)), 2)

    # Latent anomaly likelihood: unusually large amount, elevated-rate category,
    # off-hours p2p transfers, cross-border p2p/atm activity.
    usd = amount * np.vectorize(FX_TO_USD.get)(currency)
    score = (
        1.6 * (usd > 1_500).astype(float)
        + 1.2 * np.isin(category, list(ELEVATED_CATEGORIES)).astype(float)
        + 1.0 * ((channel == "p2p") & ((hour < 6) | (hour > 22))).astype(float)
        + 0.9 * ((country != "US") & np.isin(channel, ["p2p", "atm"])).astype(float)
        + 0.4 * (day / DAYS)  # drift: elevated risk in the final month
        + rng.normal(0, 0.6, N_ROWS)
    )
    p = 1 / (1 + np.exp(-2.0 * (score - 4.05)))
    anomalous = rng.random(N_ROWS) < p  # ~0.6% positive

    df = pd.DataFrame(
        {
            "txn_id": np.arange(1, N_ROWS + 1),
            "timestamp": ts,
            "customer_id": customer,
            "channel": channel,
            "category_code": category,
            "amount": amount,
            "currency": currency,
            "country": country,
        }
    )

    # Pitfall 4: only reviewed rows carry labels (all true positives were
    # reviewed; plus a random ~8% of negatives).
    reviewed = anomalous | (rng.random(N_ROWS) < 0.08)
    label = np.where(reviewed, anomalous.astype(float), np.nan)
    df["is_anomalous"] = label

    # Pitfall 1: leakage — outcome recorded *after* review.
    outcome = np.select(
        [~reviewed, anomalous],
        ["not_reviewed", "confirmed_anomaly"],
        default="dismissed",
    )
    # tiny noise so it's not literally perfect
    flip = reviewed & (rng.random(N_ROWS) < 0.01)
    outcome = np.where(flip & anomalous, "dismissed", outcome)
    df["review_outcome"] = outcome

    # Pitfall 2: exact duplicates (double-posted).
    dupes = df.sample(frac=0.015, random_state=seed)
    df = (
        pd.concat([df, dupes], ignore_index=True)
        .sort_values("timestamp")
        .reset_index(drop=True)
    )

    out = out_dir / "transactions.csv"
    df.to_csv(out, index=False)
    pos = int(np.nansum(df["is_anomalous"]))
    print(
        f"wrote {out} rows={len(df)} labeled={int(df['is_anomalous'].notna().sum())} "
        f"positives={pos} ({pos / len(df):.2%} of all rows)"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "out")
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    generate(args.out, args.seed)
