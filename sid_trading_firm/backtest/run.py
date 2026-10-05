"""Run a backtest from a YAML specification and write its report.

    python -m sid_trading_firm.backtest.run backtest.yaml --out DIR [--database]

The specification names the data, the strategy, the costs and the evaluation. Every
report carries the same disclosures, because a backtest says nothing without them.
Results are written to the ``--out`` directory (report.md, results.json; required, so
the output location is always chosen explicitly) and, with ``--database``, stored as a
research run with one row per evaluated segment and walk-forward window.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from sid_trading_firm.backtest.data import PricePanel, load_csv_directory, load_upstream_yahoo
from sid_trading_firm.backtest.engine import BacktestConfig, run_backtest
from sid_trading_firm.backtest.metrics import evaluate
from sid_trading_firm.backtest.splits import chronological_split, walk_forward, walk_forward_windows
from sid_trading_firm.quant.costs import SlippageModel, TransactionCostModel
from sid_trading_firm.strategies import create, spec_for

DISCLOSURES = [
    "Deterministic simulation: no AI model is involved in decisions or numbers.",
    "Signals use data up to each decision date; orders fill at the next open with the configured slippage and commission.",
    "Prices from Yahoo are split- and dividend-adjusted as of download, so historical price levels differ from those quoted at the time.",
    "The symbol list is chosen today: delisted companies are missing, which biases results upward (survivorship bias).",
    "Costs and slippage are the assumptions stated below, not measured execution quality.",
    "Positions still open at the end of a period are valued at the last close, not sold: no exit costs are charged. Each walk-forward test window starts from cash.",
    "In-sample (train) results are not evidence of an edge. Only validation, test and walk-forward out-of-sample results are, and one historical path is a small sample.",
    "Past results do not establish future profitability.",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DataSpec(_Strict):
    source: Literal["csv", "yahoo"]
    symbols: Annotated[list[str], Field(min_length=1)]
    path: str | None = None
    as_of: str | None = None
    on_missing: Literal["reject", "drop"] = "reject"

    @model_validator(mode="after")
    def _source_args(self) -> DataSpec:
        if self.source == "csv" and not self.path:
            raise ValueError("csv data needs a path")
        if self.source == "yahoo" and not self.as_of:
            raise ValueError("yahoo data needs as_of")
        return self


class CostSpec(_Strict):
    per_share: float = 0.0
    bps_of_notional: float = 0.0
    minimum_per_order: float = 0.0


class SlippageSpec(_Strict):
    half_spread_bps: float = 0.0
    impact_bps: float = 0.0


class EngineSpec(_Strict):
    initial_cash: float
    max_weight: float
    rebalance: Literal["daily", "weekly", "monthly"] = "monthly"
    cash_buffer: float = 0.0
    costs: CostSpec = Field(default_factory=CostSpec)
    slippage: SlippageSpec = Field(default_factory=SlippageSpec)


class StrategySpecIn(_Strict):
    id: str
    params: dict[str, Any] = Field(default_factory=dict)
    grid: list[dict[str, Any]] | None = None       # walk-forward parameter candidates


class SplitSpec(_Strict):
    train: float = 0.6
    validation: float = 0.2


class WalkForwardSpec(_Strict):
    train_days: int
    test_days: int
    step_days: int | None = None


class EvaluationSpec(_Strict):
    split: SplitSpec | None = Field(default_factory=SplitSpec)
    walk_forward: WalkForwardSpec | None = None


class BacktestSpec(_Strict):
    name: str
    data: DataSpec
    benchmark: str | None = None
    strategy: StrategySpecIn
    engine: EngineSpec
    evaluation: EvaluationSpec = Field(default_factory=EvaluationSpec)

    @model_validator(mode="after")
    def _benchmark_in_data(self) -> BacktestSpec:
        if self.benchmark and self.benchmark.upper() not in {s.upper() for s in self.data.symbols}:
            raise ValueError("the benchmark must be one of data.symbols")
        if self.evaluation.split is None and self.evaluation.walk_forward is None:
            raise ValueError("choose a split, a walk_forward, or both")
        return self


def load_spec(path: str | Path) -> BacktestSpec:
    return BacktestSpec.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def load_panel(spec: DataSpec, base: Path) -> PricePanel:
    if spec.source == "csv":
        path = Path(spec.path)
        return load_csv_directory(path if path.is_absolute() else base / path, spec.symbols, on_missing=spec.on_missing)
    return load_upstream_yahoo(spec.symbols, spec.as_of, on_missing=spec.on_missing)


def engine_config(spec: EngineSpec, **window) -> BacktestConfig:
    return BacktestConfig(
        initial_cash=spec.initial_cash, max_weight=spec.max_weight, rebalance=spec.rebalance,
        cash_buffer=spec.cash_buffer, costs=TransactionCostModel(**spec.costs.model_dump()),
        slippage=SlippageModel(**spec.slippage.model_dump()), **window)


def run(spec: BacktestSpec, base: Path = Path(".")) -> dict:
    """Evaluate the specification; returns a JSON-serialisable result."""
    panel = load_panel(spec.data, base)
    strategy = create(spec.strategy.id, spec.strategy.params)
    sspec = spec_for(strategy)
    out: dict[str, Any] = {
        "name": spec.name, "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "strategy": {"id": sspec.identifier, "params": sspec.params, "params_hash": sspec.params_hash},
        "data": {"source": panel.source, "symbols": panel.symbols, "fingerprint": panel.fingerprint(),
                 "first": str(panel.calendar()[0].date()), "last": str(panel.calendar()[-1].date()),
                 "dropped_bars": dict(panel.dropped_bars)},
        "engine": spec.engine.model_dump(), "benchmark": spec.benchmark, "segments": {}, "walk_forward": None,
        "disclosures": DISCLOSURES,
    }
    if spec.evaluation.split:
        split = chronological_split(panel.calendar(), spec.evaluation.split.train, spec.evaluation.split.validation)
        for label, period in (("train", split.train), ("validation", split.validation), ("test", split.test)):
            visible = panel.truncated(period.end)
            cfg = engine_config(spec.engine, start=str(period.start.date()), end=str(period.end.date()))
            report = evaluate(run_backtest(visible, strategy, cfg), visible, benchmark=spec.benchmark)
            out["segments"][label] = report.as_dict()
    if spec.evaluation.walk_forward:
        wf = spec.evaluation.walk_forward
        grid = spec.strategy.grid or [spec.strategy.params]
        windows = walk_forward_windows(panel.calendar(), wf.train_days, wf.test_days, wf.step_days)
        result = walk_forward(panel, lambda p: create(spec.strategy.id, p), grid, engine_config(spec.engine),
                              windows, benchmark=spec.benchmark)
        oos = result.oos_equity
        out["walk_forward"] = {
            "windows": [{"train": o.window.train.label(), "test": o.window.test.label(),
                         "chosen_params": o.chosen_params,
                         "chosen_params_hash": (spec_for(create(spec.strategy.id, o.chosen_params)).params_hash
                                                if o.chosen_params is not None else None),
                         "note": o.note,
                         "test_report": o.test_report.as_dict() if o.test_report else None}
                        for o in result.outcomes],
            "oos_metrics": {k: {"value": r.value, "status": r.status.value, "reason": r.reason}
                            for k, r in result.oos_metrics.items()},
            "oos_days": int(len(oos)),
            "oos_start": str(oos.index[0].date()) if len(oos) else None,
            "oos_end": str(oos.index[-1].date()) if len(oos) else None,
        }
    return out


def _fmt(metric: dict | None, pct: bool = False) -> str:
    if not metric:
        return "n/a"
    if metric["status"] != "ok":
        return metric["status"].replace("_", " ")
    value = metric["value"]
    return f"{value:.2%}" if pct else f"{value:,.4f}"


ROWS = [("total_return", True), ("annualised_return", True), ("benchmark_return", True), ("excess_return", True),
        ("volatility", True), ("sharpe", False), ("sortino", False), ("max_drawdown", True), ("win_rate", True),
        ("profit_factor", False), ("expectancy", False), ("trade_count", False), ("turnover", False),
        ("total_commission", False), ("total_slippage", False)]


def render_report(result: dict) -> str:
    lines = [f"# Backtest: {result['name']}", "",
             f"Strategy `{result['strategy']['id']}` (params hash `{result['strategy']['params_hash']}`), "
             f"data {result['data']['source']} {result['data']['first']}..{result['data']['last']}, "
             f"fingerprint `{result['data']['fingerprint']}`, benchmark {result['benchmark'] or 'none'}.", "",
             "## Disclosures", "", *[f"- {d}" for d in result["disclosures"]], "",
             "## Assumptions", "", f"```json\n{json.dumps(result['engine'], indent=2)}\n```", "",
             f"Parameters: `{json.dumps(result['strategy']['params'], sort_keys=True)}`", ""]
    if result["segments"]:
        names = list(result["segments"])
        lines += ["## Train / validation / test", "",
                  "Train is in-sample. Parameters were not tuned on validation or test.", "",
                  "| Metric | " + " | ".join(names) + " |", "|---|" + "---:|" * len(names)]
        for key, pct in ROWS:
            lines.append(f"| {key} | " + " | ".join(_fmt(result["segments"][n]["metrics"].get(key), pct)
                                                     for n in names) + " |")
        lines += ["", "Periods: " + ", ".join(f"{n} {result['segments'][n]['start']}..{result['segments'][n]['end']}"
                                              for n in names), ""]
        for n in names:
            if result["segments"][n]["regimes"]:
                lines.append(f"Regimes ({n}): `{json.dumps(result['segments'][n]['regimes'])}`")
        lines.append("")
    wf = result.get("walk_forward")
    if wf:
        lines += ["## Walk-forward (out of sample)", "",
                  f"{len(wf['windows'])} window(s), {wf['oos_days']} out-of-sample trading days.", "",
                  "| Train | Test | Chosen params | Test return |", "|---|---|---|---:|"]
        for w in wf["windows"]:
            ret = (_fmt(w["test_report"]["metrics"].get("total_return"), True) if w["test_report"]
                   else (w["note"] or "n/a"))
            lines.append(f"| {w['train']} | {w['test']} | `{json.dumps(w['chosen_params'], sort_keys=True)}` | {ret} |")
        lines += ["", "Stitched out-of-sample: " + ", ".join(
            f"{k} {_fmt(v, k != 'sharpe')}" for k, v in wf["oos_metrics"].items()), ""]
    return "\n".join(lines)


def store(result: dict, spec: BacktestSpec) -> str:
    """Persist as a research run (kind 'backtest') with one row per segment; returns the run id."""
    from sid_trading_firm.config import load_settings
    from sid_trading_firm.persistence import Database, RunRepository, engine_from_settings
    from sid_trading_firm.persistence.backtests import BacktestRepository
    from sid_trading_firm.runtime import run_context

    settings = load_settings()
    db = Database(engine_from_settings(settings))
    runs, repo = RunRepository(db), BacktestRepository(db)
    strategy_id, source = result["strategy"]["id"], result["data"]["source"]
    with run_context(strategy=strategy_id, environment=settings.app.environment.value) as run:
        runs.start(run, kind="backtest", settings=settings)
        try:
            vid = repo.strategy_version(strategy_id, result["strategy"]["params"], result["strategy"]["params_hash"])
            for segment, report in result["segments"].items():
                repo.record(run_id=run.run_id, version_id=vid, segment=segment, report=report,
                            config=result["engine"], data_source=source)
            wf = result["walk_forward"]
            if wf:
                for w in wf["windows"]:
                    if w["test_report"] is None:
                        continue
                    wid = repo.strategy_version(strategy_id, w["chosen_params"], w["chosen_params_hash"])
                    repo.record(run_id=run.run_id, version_id=wid, segment="walk_forward_window",
                                report=w["test_report"], config=result["engine"], data_source=source,
                                notes=f"train {w['train']}; parameters chosen on the training window only")
                if wf["oos_start"]:
                    oos_report = {"start": wf["oos_start"], "end": wf["oos_end"],
                                  "data_fingerprint": result["data"]["fingerprint"], "metrics": wf["oos_metrics"]}
                    repo.record(run_id=run.run_id, version_id=vid, segment="walk_forward_oos", report=oos_report,
                                config=result["engine"], data_source=source,
                                notes="stitched test windows; each window's parameters are in its "
                                      "walk_forward_window row")
        except BaseException as exc:
            runs.finish(run.run_id, status="failed", error=f"{type(exc).__name__}: {exc}")
            raise
        runs.finish(run.run_id, status="completed",
                    summary={"name": result["name"], "segments": list(result["segments"]),
                             "walk_forward_windows": len(wf["windows"]) if wf else 0})
        return run.run_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("spec")
    parser.add_argument("--out", type=Path, required=True, help="directory for report.md and results.json")
    parser.add_argument("--database", action="store_true", help="also store the results (needs SID_DATABASE__URL)")
    args = parser.parse_args(argv)
    spec_path = Path(args.spec)
    spec = load_spec(spec_path)
    result = run(spec, base=spec_path.parent)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    (out / "report.md").write_text(render_report(result) + "\n", encoding="utf-8")
    if args.database:
        result["run_id"] = store(result, spec)
    print(f"report: {out / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
