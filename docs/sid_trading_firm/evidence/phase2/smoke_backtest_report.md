<!--
PIPELINE SMOKE TEST OUTPUT. NOT EVIDENCE OF A TRADING EDGE.
Produced on 2026-10-05 by running, on main 87936cf:
  python -m sid_trading_firm.backtest.run docs/sid_trading_firm/examples/backtest_momentum.yaml --out <scratch>
Purpose: show the Phase 2 pipeline end to end on real (free, Yahoo) daily data.
The symbol list is nine of today's largest US companies chosen in hindsight: the
results are dominated by survivorship and selection bias and say nothing about
whether momentum_v1 has an edge. No AI model was called; nothing was traded.
-->

# Backtest: momentum_example

Strategy `momentum_v1` (params hash `49d22532cc0d2686`), data yahoo (adjusted) 2021-10-05..2026-09-30, fingerprint `c2752ed22a7ae590`, benchmark SPY.

## Disclosures

- Deterministic simulation: no AI model is involved in decisions or numbers.
- Signals use data up to each decision date; orders fill at the next open with the configured slippage and commission.
- Prices from Yahoo are split- and dividend-adjusted as of download, so historical price levels differ from those quoted at the time.
- The symbol list is chosen today: delisted companies are missing, which biases results upward (survivorship bias).
- Costs and slippage are the assumptions stated below, not measured execution quality.
- Positions still open at the end of a period are valued at the last close, not sold: no exit costs are charged. Each walk-forward test window starts from cash.
- In-sample (train) results are not evidence of an edge. Only validation, test and walk-forward out-of-sample results are, and one historical path is a small sample.
- Past results do not establish future profitability.

## Assumptions

```json
{
  "initial_cash": 100000.0,
  "max_weight": 0.34,
  "rebalance": "monthly",
  "cash_buffer": 0.0,
  "costs": {
    "per_share": 0.005,
    "bps_of_notional": 0.0,
    "minimum_per_order": 1.0
  },
  "slippage": {
    "half_spread_bps": 2.0,
    "impact_bps": 3.0
  }
}
```

Parameters: `{"lookback": 252, "require_positive": true, "skip": 21, "top_n": 3, "universe": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM", "XOM", "UNH"]}`

## Train / validation / test

Train is in-sample. Parameters were not tuned on validation or test.

| Metric | train | validation | test |
|---|---:|---:|---:|
| total_return | 130.08% | 27.94% | 3.36% |
| annualised_return | 32.31% | 28.32% | 3.39% |
| benchmark_return | 38.45% | 18.58% | 15.32% |
| excess_return | 91.63% | 9.36% | -11.96% |
| volatility | 20.28% | 30.09% | 18.78% |
| sharpe | 1.4815 | 0.9776 | 0.2711 |
| sortino | 2.4795 | 1.4750 | 0.3831 |
| max_drawdown | 16.50% | 29.88% | 14.80% |
| win_rate | 80.00% | 70.00% | 81.25% |
| profit_factor | 3.6724 | 1.5757 | 1.3371 |
| expectancy | 1,057.7129 | 307.4778 | 142.2666 |
| trade_count | 35.0000 | 20.0000 | 16.0000 |
| turnover | 3.4644 | 5.2591 | 6.0952 |
| total_commission | 89.1050 | 43.5000 | 40.3550 |
| total_slippage | 669.3328 | 294.9570 | 311.6362 |

Periods: train 2021-10-05..2024-09-30, validation 2024-10-01..2025-09-30, test 2025-10-01..2026-09-30

Regimes (train): `{"above_trend": {"days": 426, "compounded_return": 1.2449641452950977, "mean_daily_return": 0.00203593792507036, "annualised_return": 0.61345805177592}, "below_trend": {"days": 125, "compounded_return": 0.024858775763283214, "mean_daily_return": 0.00021565339827843034, "annualised_return": 0.05074824417725621}, "unknown": {"days": 199, "compounded_return": 0.0, "mean_daily_return": 0.0, "annualised_return": 0.0}}`
Regimes (validation): `{"above_trend": {"days": 207, "compounded_return": 0.19612572528028527, "mean_daily_return": 0.0009663491388841922, "annualised_return": 0.24361180991179765}, "below_trend": {"days": 42, "compounded_return": 0.06963186618540251, "mean_daily_return": 0.002157283513042666, "annualised_return": 0.4976350549495909}}`
Regimes (test): `{"above_trend": {"days": 238, "compounded_return": 0.001735207128006122, "mean_daily_return": 7.707091219320874e-05, "annualised_return": 0.0018373718509496761}, "below_trend": {"days": 12, "compounded_return": 0.03182522720330749, "mean_daily_return": 0.0026814792311903126, "annualised_return": 0.9307630430532821}}`

## Walk-forward (out of sample)

5 window(s), 630 out-of-sample trading days.

| Train | Test | Chosen params | Test return |
|---|---|---|---:|
| 2021-10-05..2023-10-05 | 2023-10-06..2024-04-08 | `{"lookback": 126, "skip": 21, "top_n": 3, "universe": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM", "XOM", "UNH"]}` | 50.86% |
| 2022-04-05..2024-04-08 | 2024-04-09..2024-10-07 | `{"lookback": 126, "skip": 21, "top_n": 3, "universe": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM", "XOM", "UNH"]}` | 13.53% |
| 2022-10-05..2024-10-07 | 2024-10-08..2025-04-09 | `{"lookback": 252, "skip": 21, "top_n": 3, "universe": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM", "XOM", "UNH"]}` | -6.05% |
| 2023-04-06..2025-04-09 | 2025-04-10..2025-10-09 | `{"lookback": 126, "skip": 21, "top_n": 3, "universe": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM", "XOM", "UNH"]}` | 21.62% |
| 2023-10-06..2025-10-09 | 2025-10-10..2026-04-13 | `{"lookback": 252, "skip": 21, "top_n": 3, "universe": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM", "XOM", "UNH"]}` | 9.40% |

Stitched out-of-sample: total_return 114.12%, volatility 27.72%, sharpe 1.2386, max_drawdown 29.91%

