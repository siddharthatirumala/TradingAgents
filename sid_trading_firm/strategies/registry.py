"""Strategy identities, parameter hashing and the governance lifecycle (GOVERNANCE.md section 15).

Strategy parameters are part of a strategy's identity: they are hashed into
``params_hash`` and stored. A credential must never reach either, and masking it after
hashing would not help (the raw value would already have shaped the hash). So
parameters that carry a credential (a credential-named key, or a value or key the
credential masker would change) are refused with :class:`CredentialParameterError`
before any hash is computed or any strategy is built. The error names the offending
paths, never the values.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, fields
from enum import StrEnum
from typing import Any

from sid_trading_firm.persistence.sanitize import credential_paths
from sid_trading_firm.strategies.reference import BuyAndHoldV1, MomentumV1

REGISTRY: dict[str, type] = {
    "momentum_v1": MomentumV1,
    "buy_and_hold_v1": BuyAndHoldV1,
}

_IDENTITY_FIELDS = {"name", "version"}


class CredentialParameterError(ValueError):
    """Strategy parameters that carry a credential; refused before hashing or persistence."""


def reject_credentials(params: Mapping[str, Any], *, where: str = "strategy parameters") -> None:
    """Raise :class:`CredentialParameterError` if ``params`` carry a credential anywhere."""
    paths = credential_paths(_jsonable(params))
    if paths:
        raise CredentialParameterError(
            f"{where} must not carry credentials; refused at {', '.join(paths)}")


class StrategyStatus(StrEnum):
    """Lifecycle from GOVERNANCE.md section 15. Live states need separate governance."""

    PROPOSED = "PROPOSED"
    BACKTESTED = "BACKTESTED"
    VALIDATED = "VALIDATED"
    PAPER_APPROVED = "PAPER_APPROVED"
    PAPER_ACTIVE = "PAPER_ACTIVE"
    RETIRED = "RETIRED"


@dataclass(frozen=True)
class StrategySpec:
    identifier: str
    params: Mapping[str, Any]

    def __post_init__(self) -> None:
        reject_credentials(self.params, where=f"{self.identifier} parameters")

    @property
    def params_hash(self) -> str:
        canonical = json.dumps(_jsonable(self.params), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(f"{self.identifier}|{canonical}".encode()).hexdigest()[:16]


def _jsonable(value):
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def create(identifier: str, params: Mapping[str, Any] | None = None):
    """Instantiate a registered strategy; unknown identifiers and parameters are errors."""
    try:
        cls = REGISTRY[identifier]
    except KeyError:
        raise KeyError(f"unknown strategy {identifier!r}; known: {sorted(REGISTRY)}") from None
    params = dict(params or {})
    reject_credentials(params, where=f"{identifier} parameters")
    allowed = {f.name for f in fields(cls)} - _IDENTITY_FIELDS
    unknown = set(params) - allowed
    if unknown:
        raise ValueError(f"{identifier}: unknown parameters {sorted(unknown)}")
    for key in ("universe", "symbols"):
        if isinstance(params.get(key), list):
            params[key] = tuple(params[key])
    return cls(**params)


def spec_for(strategy) -> StrategySpec:
    """The identity and full parameter set of a strategy instance (defaults included)."""
    params = {f.name: getattr(strategy, f.name) for f in fields(strategy) if f.name not in _IDENTITY_FIELDS}
    return StrategySpec(f"{strategy.name}_{strategy.version}", params)
