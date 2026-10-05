"""Credential-bearing strategy parameters are refused before identity hashing and persistence.

All credentials are synthetic and assembled at runtime. A refused parameter set must
not reach a strategy, a params_hash, the database or an output file, and the error
names paths only, never values.
"""

import hashlib
import json

import pytest
import yaml
from sqlalchemy import text

from sid_trading_firm.backtest import run as runner
from sid_trading_firm.persistence import Database, make_engine
from sid_trading_firm.persistence.backtests import BacktestRepository
from sid_trading_firm.persistence.migrate import upgrade
from sid_trading_firm.persistence.models import Base
from sid_trading_firm.persistence.sanitize import credential_paths, sanitize
from sid_trading_firm.strategies import CredentialParameterError, StrategySpec, create, spec_for
from tests_sid.test_backtest_run import spec_dict, write_synthetic_csvs

pytestmark = pytest.mark.unit

SECRET = "synth" + "-param-secret-58"
PROVIDER_KEY = "sk-ant-api03-" + "Synthetic" + "0123456789abcdef"


def credential_cases():
    return [
        ({"api_key": SECRET}, "$.api_key"),
        ({"window": 20, "source": {"token": SECRET}}, "$.source.token"),
        ({"Authorization": "Bearer " + SECRET}, "$.Authorization"),
        ({"notes": ["fine", "password='" + SECRET + "'"]}, "$.notes[1]"),
        ({"url": "postgresql://user:" + SECRET + "@db.internal/sid"}, "$.url"),
        ({"model": PROVIDER_KEY}, "$.model"),
        ({"deep": [{"x": {"client_secret": SECRET}}]}, "$.deep[0].x.client_secret"),
        ({"password=" + SECRET: 1}, "$.<credential-shaped key>"),
    ]


def raw_hash(identifier, params):
    """What params_hash would have been for these raw parameters (the hash-derived secret)."""
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{identifier}|{canonical}".encode()).hexdigest()[:16]


# ------------------------------------------------------------------ detection

@pytest.mark.parametrize("params, path", credential_cases())
def test_credential_paths_name_the_location_never_the_value(params, path):
    paths = credential_paths(params)
    assert paths == [path]
    assert SECRET not in str(paths) and PROVIDER_KEY not in str(paths)


def test_ordinary_parameters_carry_no_credential():
    for params in ({"lookback": 252, "skip": 21, "top_n": 5, "universe": ["AAPL", "BRK-B"]},
                   {"symbols": ("SPY",), "require_positive": True, "note": "monthly rebalance"},
                   {"max_tokens": 10, "tokenizer": "none", "secretary": None}):
        assert credential_paths(params) == []


def test_nesting_deeper_than_the_masker_inspects_is_refused():
    deep: dict = {"v": 1}
    for _ in range(25):
        deep = {"n": deep}
    assert credential_paths(deep) and "nested too deeply" in credential_paths(deep)[0]


# ------------------------------------------------------------------ refused before hashing

@pytest.mark.parametrize("params, path", credential_cases())
def test_a_strategy_identity_refuses_credentials_before_hashing(params, path):
    with pytest.raises(CredentialParameterError) as info:
        StrategySpec("custom_v1", params)             # params_hash is never reachable
    assert path in str(info.value) and SECRET not in str(info.value) and PROVIDER_KEY not in str(info.value)


@pytest.mark.parametrize("identifier, params", [
    ("buy_and_hold_v1", {"symbols": ["SPY", "postgresql://u:" + SECRET + "@h/db"]}),
    ("momentum_v1", {"universe": ["AAPL", PROVIDER_KEY]}),
    ("momentum_v1", {"api_key": SECRET}),             # refused as a credential, before "unknown parameter"
])
def test_create_refuses_credentials_before_building_a_strategy(identifier, params):
    with pytest.raises(CredentialParameterError) as info:
        create(identifier, params)
    assert SECRET not in str(info.value) and PROVIDER_KEY not in str(info.value)


def test_ordinary_parameters_hash_and_create_as_before():
    spec = spec_for(create("momentum_v1", {"lookback": 60, "skip": 5, "universe": ["A", "B"]}))
    assert spec.params_hash == StrategySpec("momentum_v1", dict(spec.params)).params_hash
    assert spec.params_hash == raw_hash("momentum_v1", json.loads(json.dumps(
        {k: list(v) if isinstance(v, tuple) else v for k, v in spec.params.items()})))


# ------------------------------------------------------------------ repository: nothing persisted

def _db_text(db) -> str:
    with db.engine.connect() as c:
        rows = []
        for table in ("strategy_versions", "backtest_results", "research_runs", "audit_events", "llm_usage"):
            rows += [str(r) for r in c.execute(text(f"SELECT * FROM {table}")).all()]
    return "\n".join(rows)


@pytest.fixture
def db():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    yield Database(engine)
    engine.dispose()


@pytest.mark.parametrize("params, path", credential_cases())
def test_the_repository_refuses_credentials_and_persists_nothing(db, params, path):
    repo = BacktestRepository(db)
    for offered_hash in (raw_hash("custom_v1", params), "0" * 16):
        with pytest.raises(CredentialParameterError):
            repo.strategy_version("custom_v1", params, offered_hash)
    stored = _db_text(db)
    assert stored == ""                                   # no row of any kind was written
    assert SECRET not in stored and PROVIDER_KEY not in stored and raw_hash("custom_v1", params) not in stored


def test_the_repository_refuses_a_hash_that_is_not_derived_from_the_parameters(db):
    repo = BacktestRepository(db)
    spec = spec_for(create("buy_and_hold_v1", {"symbols": ["SPY"]}))
    with pytest.raises(ValueError, match="params_hash does not match"):
        repo.strategy_version(spec.identifier, spec.params, raw_hash("x", {"api_key": SECRET}))
    assert _db_text(db) == ""


def test_ordinary_parameters_stay_idempotent_and_are_stored_unchanged(db):
    repo = BacktestRepository(db)
    spec = spec_for(create("momentum_v1", {"lookback": 60, "skip": 5, "top_n": 2, "universe": ["AAA", "BBB"]}))
    vid = repo.strategy_version(spec.identifier, spec.params, spec.params_hash)
    assert repo.strategy_version(spec.identifier, spec.params, spec.params_hash) == vid
    row = repo.get_version(vid)
    assert row.params_hash == spec.params_hash and row.params["universe"] == ["AAA", "BBB"]
    assert row.params == sanitize(row.params)              # nothing left that masking would change


# ------------------------------------------------------------------ end to end: no run, no files

def test_the_runner_refuses_credential_parameters_before_any_run_or_file(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    write_synthetic_csvs(tmp_path / "data")
    spec = spec_dict()
    spec["strategy"]["params"]["universe"] = ["AAA", "BBB", "postgresql://u:" + SECRET + "@h/db"]
    spec_file = tmp_path / "spec.yaml"
    spec_file.write_text(yaml.safe_dump(spec), encoding="utf-8")
    url = f"sqlite:///{(tmp_path / 'sid.db').as_posix()}"
    upgrade(url)
    monkeypatch.setenv("SID_DATABASE__URL", url)
    out = tmp_path / "out"

    with pytest.raises(CredentialParameterError) as info:
        runner.main([str(spec_file), "--out", str(out), "--database"])
    assert SECRET not in str(info.value)
    assert not out.exists()
    engine = make_engine(url)
    try:
        assert _db_text(Database(engine)) == ""
    finally:
        engine.dispose()
