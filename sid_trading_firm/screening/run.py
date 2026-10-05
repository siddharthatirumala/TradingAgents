"""Run a screen from a YAML specification and write its report.

    python -m sid_trading_firm.screening.run screen.yaml --out DIR [--database]

The specification names the universe file, the price data, the screening date, the
filter thresholds, the factor weights and the candidate limits. Results are written
to the ``--out`` directory (report.md, results.json; required, so the output location
is always chosen explicitly). With ``--database`` the screen is stored first, as a
research run of kind ``screen`` with its ranked candidates, and the files carry the
database ``run_id``; if storing fails, the files are written marked as not stored and
the command exits with the error. Every file is written whole or not at all. No AI
model is called.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, Field

from sid_trading_firm.backtest.run import DataSpec, StorageError, load_panel, write_atomically
from sid_trading_firm.screening.filters import FilterConfig
from sid_trading_firm.screening.scoring import ScoringConfig
from sid_trading_firm.screening.screen import ScreenResult, run_screen
from sid_trading_firm.screening.universe import load_universe

DISCLOSURES = [
    "Deterministic screen: no AI model is involved in filtering, scoring or selection.",
    "Every measure uses data on or before the screening date.",
    "Candidates are symbols selected for later research, not recommendations or trade signals.",
    "Factor scores are percentile ranks within the symbols that passed the filters on this date only.",
    "The research-cost estimate per candidate is an input from measurement, not a price quote.",
]


class ScreenSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    universe: str
    data: DataSpec
    as_of: str
    filters: FilterConfig = Field(default_factory=FilterConfig)
    scoring: ScoringConfig
    max_candidates: Annotated[int, Field(ge=1)]
    research_cost_per_candidate_usd: Annotated[Decimal, Field(gt=0)]


def load_spec(path: str | Path) -> ScreenSpec:
    return ScreenSpec.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def result_dict(spec: ScreenSpec, screen: ScreenResult, data_source: str) -> dict:
    return {
        "name": spec.name, "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "as_of": screen.as_of, "universe": screen.universe, "universe_fingerprint": screen.universe_fingerprint,
        "data_source": data_source, "data_fingerprint": screen.data_fingerprint,
        "config_fingerprint": screen.config_fingerprint, "inputs_fingerprint": screen.inputs_fingerprint,
        "config": {"filters": spec.filters.model_dump(), "scoring": spec.scoring.model_dump(),
                   "max_candidates": spec.max_candidates,
                   "research_cost_per_candidate_usd": str(spec.research_cost_per_candidate_usd)},
        "funnel": screen.funnel,
        "selected": [{"symbol": s.symbol, "composite": s.composite, "ranks": s.ranks, "raw": s.raw}
                     for s in screen.selected],
        "rejected": {o.symbol: o.reasons for o in screen.outcomes if not o.passed},
        "excluded": dict(screen.scoring.excluded),
        "missing_data": screen.missing_data,
        "measures": {o.symbol: o.measures for o in screen.outcomes},
        "cost": screen.cost,
        "disabled_filters": screen.disabled_filters,
        "survivorship_note": screen.survivorship_note,
        "disclosures": DISCLOSURES,
    }


def run(spec: ScreenSpec, base: Path = Path("."), *, budgets=None) -> dict:
    """Run the screen; ``budgets`` defaults to the loaded settings' budgets."""
    if budgets is None:
        from sid_trading_firm.config import load_settings

        budgets = load_settings().budgets
    universe_path = Path(spec.universe)
    universe = load_universe(universe_path if universe_path.is_absolute() else base / universe_path)
    panel = load_panel(spec.data, base)
    screen = run_screen(universe, panel, spec.as_of, spec.filters, spec.scoring,
                        max_candidates=spec.max_candidates,
                        research_cost_per_candidate_usd=spec.research_cost_per_candidate_usd, budgets=budgets)
    return result_dict(spec, screen, panel.source)


def _persistence_lines(result: dict) -> list[str]:
    p = result.get("persistence") or {}
    if p.get("status") == "stored":
        return [f"Stored in the database as research run `{p['run_id']}`.", ""]
    if p.get("status") == "failed":
        failed_run = f" Research run `{p['run_id']}` is marked failed." if p.get("run_id") else ""
        return [f"> **STORAGE FAILED. This screen was not stored in the database.**{failed_run} "
                f"Error: {p.get('error')}", ""]
    return ["Not stored in the database (run without `--database`).", ""]


def render_report(result: dict) -> str:
    f = result["funnel"]
    lines = [f"# Screen: {result['name']}", "", *_persistence_lines(result),
             f"Screening date {result['as_of']}, universe `{result['universe']}` "
             f"(fingerprint `{result['universe_fingerprint']}`), data {result['data_source']} "
             f"(fingerprint `{result['data_fingerprint']}`), inputs fingerprint `{result['inputs_fingerprint']}`.", "",
             "## Disclosures", "", *[f"- {d}" for d in result["disclosures"]],
             f"- {result['survivorship_note']}", "",
             "## Funnel", "", "| Stage | Symbols |", "|---|---:|",
             *[f"| {stage.replace('_', ' ')} | {count} |" for stage, count in f.items()], "",
             "## Candidates for research", ""]
    if result["selected"]:
        factors = list(result["selected"][0]["ranks"])
        lines += ["| Rank | Symbol | Composite | " + " | ".join(f"{n} (rank)" for n in factors) + " |",
                  "|---:|---|---:|" + "---:|" * len(factors)]
        for i, c in enumerate(result["selected"], start=1):
            lines.append(f"| {i} | {c['symbol']} | {c['composite']:.3f} | "
                         + " | ".join(f"{c['ranks'][n]:.2f}" for n in factors) + " |")
    else:
        lines.append("No symbol passed the filters and scoring.")
    cost = result["cost"]
    lines += ["", "## Research budget", "",
              f"{cost['selected']} candidate(s) x ${cost['per_candidate_usd']} estimated = "
              f"${cost['estimated_total_usd']}; limit {cost['limit']} set by {cost['limited_by']}.", "",
              "## Configuration", "", f"```json\n{json.dumps(result['config'], indent=2)}\n```", "",
              "Disabled filters: " + (", ".join(result["disabled_filters"]) or "none"), ""]
    if result["rejected"] or result["excluded"] or result["missing_data"]:
        lines += ["## Not selected", "", "| Symbol | Reason |", "|---|---|"]
        lines += [f"| {s} | {'; '.join(r)} |" for s, r in sorted(result["rejected"].items())]
        lines += [f"| {s} | {r} |" for s, r in sorted(result["excluded"].items())]
        lines += [f"| {s} | no price data |" for s in result["missing_data"]]
        lines.append("")
    return "\n".join(lines)


def store(result: dict) -> str:
    """Persist as a research run (kind 'screen') with its candidates; returns the run id."""
    from sid_trading_firm.config import load_settings
    from sid_trading_firm.persistence import Database, RunRepository, engine_from_settings
    from sid_trading_firm.persistence.screening import ScreeningRepository
    from sid_trading_firm.runtime import run_context

    settings = load_settings()
    db = Database(engine_from_settings(settings))
    runs, repo = RunRepository(db), ScreeningRepository(db)
    with run_context(strategy=f"screen:{result['name']}", environment=settings.app.environment.value) as run:
        runs.start(run, kind="screen", settings=settings)
        try:
            repo.record(run_id=run.run_id, result=result, data_source=result["data_source"])
        except Exception as exc:
            runs.finish(run.run_id, status="failed", error=f"{type(exc).__name__}: {exc}")
            raise StorageError(f"{type(exc).__name__}: {exc}", run.run_id) from exc
        runs.finish(run.run_id, status="completed",
                    summary={"name": result["name"], "as_of": result["as_of"],
                             "selected": [c["symbol"] for c in result["selected"]]})
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
    failure: Exception | None = None
    result["persistence"] = {"status": "not_requested", "run_id": None}
    if args.database:
        try:
            result["persistence"] = {"status": "stored", "run_id": store(result)}
        except Exception as exc:    # write the files marked as not stored, then fail
            from sid_trading_firm.persistence.sanitize import sanitize_text

            failure = exc
            result["persistence"] = {"status": "failed", "run_id": getattr(exc, "run_id", None),
                                     "error": sanitize_text(f"{type(exc).__name__}: {exc}")}
    args.out.mkdir(parents=True, exist_ok=True)
    write_atomically(args.out / "results.json", json.dumps(result, indent=2, default=str))
    write_atomically(args.out / "report.md", render_report(result) + "\n")
    if failure is not None:
        print(f"STORAGE FAILED; the files in {args.out} are marked as not stored", file=sys.stderr)
        raise failure
    print(f"report: {args.out / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
