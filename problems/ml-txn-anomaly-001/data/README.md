# Data dictionary — `transactions.csv`

Six months of payments-platform transactions (Nov 2025 – Apr 2026), ~406k rows.

| Column | Type | Description |
|---|---|---|
| `txn_id` | int | Transaction identifier |
| `timestamp` | datetime | Event time (UTC) |
| `customer_id` | int | Customer identifier |
| `channel` | str | `card`, `wire`, `ach`, `atm`, `p2p` |
| `category_code` | int | Transaction category code (opaque) |
| `amount` | float | Transaction amount **in native currency** |
| `currency` | str | `USD`, `EUR`, `GBP` |
| `country` | str | ISO country where the transaction was processed |
| `is_anomalous` | float | Review label: `1.0` confirmed anomalous, `0.0` dismissed, empty if never reviewed |
| `review_outcome` | str | Review status: `confirmed_anomaly`, `dismissed`, `not_reviewed` |

Data is exported as-is from the review system; assess quality yourself.
