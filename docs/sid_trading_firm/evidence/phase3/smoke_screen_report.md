<!--
PIPELINE SMOKE TEST OUTPUT. NOT A RECOMMENDATION AND NOT EVIDENCE OF AN EDGE.
Produced on 2026-10-05 by running, on main 8c8157f:
  python -m sid_trading_firm.screening.run docs/sid_trading_firm/examples/screen_large_cap.yaml --out <scratch>
Purpose: show the Phase 3 pipeline end to end on real (free, Yahoo) daily data over the
hand-compiled, survivorship-biased seed universe. No AI model was called; nothing was traded.
-->

# Screen: large_cap_example

Screening date 2026-09-30, universe `us_large_cap_seed_v1` (fingerprint `7afcf528ad0a8db0`), data yahoo (adjusted) (fingerprint `362f4f60e2372773`), inputs fingerprint `a86e45879b3c8a9c`.

## Disclosures

- Deterministic screen: no AI model is involved in filtering, scoring or selection.
- Every measure uses data on or before the screening date.
- Candidates are symbols selected for later research, not recommendations or trade signals.
- Factor scores are percentile ranks within the symbols that passed the filters on this date only.
- The research-cost estimate per candidate is an input from measurement, not a price quote.
- Survivorship bias: this list was compiled on its as_of date from companies that exist and are large today. Screening it over earlier dates excludes companies that were delisted, acquired or shrank, which overstates historical results.

## Funnel

| Stage | Symbols |
|---|---:|
| universe | 33 |
| eligible common stocks | 31 |
| with data | 31 |
| passed filters | 31 |
| scored | 31 |
| selected | 5 |

## Candidates for research

| Rank | Symbol | Composite | momentum (rank) | trend (rank) | low_volatility (rank) |
|---:|---|---:|---:|---:|---:|
| 1 | JNJ | 0.833 | 0.87 | 0.77 | 0.83 |
| 2 | MRK | 0.825 | 1.00 | 1.00 | 0.30 |
| 3 | CSCO | 0.767 | 0.93 | 0.80 | 0.40 |
| 4 | CVX | 0.750 | 0.77 | 0.83 | 0.63 |
| 5 | KO | 0.742 | 0.73 | 0.70 | 0.80 |

## Research budget

5 candidate(s) x $0.80 estimated = $4.00; limit 5 set by max_candidates, budgets.max_ai_candidates_per_run.

## Configuration

```json
{
  "filters": {
    "min_price": 5.0,
    "min_avg_dollar_volume": 50000000.0,
    "max_annualised_volatility": 0.8,
    "min_history_days": 260,
    "max_data_age_days": 5,
    "liquidity_window": 20,
    "volatility_window": 60
  },
  "scoring": {
    "factors": {
      "momentum": {
        "weight": 2.0,
        "params": {}
      },
      "trend": {
        "weight": 1.0,
        "params": {}
      },
      "low_volatility": {
        "weight": 1.0,
        "params": {}
      }
    }
  },
  "max_candidates": 5,
  "research_cost_per_candidate_usd": "0.80"
}
```

Disabled filters: none

