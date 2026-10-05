"""Price data for deterministic backtests, with point-in-time access only.

A :class:`PricePanel` holds validated daily OHLCV bars per symbol. Strategies never
see the panel itself: they get a :class:`PanelView` fixed at one date, which can only
return bars dated on or before it. Look-ahead is therefore impossible by
construction, not by convention, and the view records the latest date it served so
tests can prove a period was never read.

Data limitations (also stated in every backtest report):
- Prices from Yahoo are split- and dividend-adjusted as of download time, so price
  *levels* before a later split differ from what was quoted then; returns are right.
- A universe given as today's symbols carries survivorship bias: companies that were
  delisted are missing. Phase 2 backtests run on an explicit symbol list and say so.
"""

from __future__ import annotations

import hashlib
import io
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pandas as pd

FIELDS = ("open", "high", "low", "close", "volume")
MissingPolicy = Literal["reject", "drop"]


class DataError(ValueError):
    """Price data that a backtest must not run on."""


def _normalise(symbol: str, frame: pd.DataFrame, on_missing: MissingPolicy) -> tuple[pd.DataFrame, int]:
    df = frame.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "date" in df.columns:
        df = df.set_index("date")
    missing = [f for f in FIELDS if f not in df.columns]
    if missing:
        raise DataError(f"{symbol}: missing columns {missing}")
    df = df[list(FIELDS)]
    try:
        index = pd.to_datetime(df.index)
    except (TypeError, ValueError) as exc:
        raise DataError(f"{symbol}: dates are not parseable ({exc})") from None
    if getattr(index, "tz", None) is not None:
        index = index.tz_localize(None)
    df.index = index.normalize()
    df.index.name = "date"
    if df.index.has_duplicates:
        raise DataError(f"{symbol}: duplicate dates {sorted(set(df.index[df.index.duplicated()].date))[:3]}")
    df = df.sort_index()
    try:
        df = df.astype(float)
    except (TypeError, ValueError) as exc:
        raise DataError(f"{symbol}: non-numeric values ({exc})") from None
    incomplete = df.isna().any(axis=1)
    dropped = int(incomplete.sum())
    if dropped:
        if on_missing == "reject":
            raise DataError(f"{symbol}: {dropped} bar(s) with missing values")
        df = df[~incomplete]
    if df.empty:
        raise DataError(f"{symbol}: no complete bars")
    values = df.to_numpy()
    if not all(math.isfinite(v) for v in values.ravel()):
        raise DataError(f"{symbol}: infinite values")
    prices = df[["open", "high", "low", "close"]]
    if (prices <= 0).any().any():
        raise DataError(f"{symbol}: non-positive prices")
    if (df["volume"] < 0).any():
        raise DataError(f"{symbol}: negative volume")
    if (df["high"] < df["low"]).any():
        raise DataError(f"{symbol}: high below low")
    tolerance = 1e-9 * df["high"]
    outside = ((df["open"] > df["high"] + tolerance) | (df["open"] < df["low"] - tolerance)
               | (df["close"] > df["high"] + tolerance) | (df["close"] < df["low"] - tolerance))
    if outside.any():
        raise DataError(f"{symbol}: open/close outside the high-low range on {int(outside.sum())} bar(s)")
    return df, dropped


@dataclass(frozen=True)
class PricePanel:
    """Validated daily bars, one frame per symbol (columns open, high, low, close, volume)."""

    frames: Mapping[str, pd.DataFrame]
    dropped_bars: Mapping[str, int] = field(default_factory=dict)
    source: str = "frames"

    @classmethod
    def from_frames(cls, frames: Mapping[str, pd.DataFrame], *, on_missing: MissingPolicy = "reject",
                    source: str = "frames") -> PricePanel:
        if not frames:
            raise DataError("no symbols")
        if on_missing not in ("reject", "drop"):
            raise DataError(f"unknown on_missing policy {on_missing!r}")
        clean, dropped = {}, {}
        for symbol, frame in frames.items():
            if not isinstance(symbol, str) or not symbol.strip():
                raise DataError(f"invalid symbol {symbol!r}")
            clean[symbol.upper()], dropped[symbol.upper()] = _normalise(symbol, frame, on_missing)
        return cls(clean, dropped, source)

    @property
    def symbols(self) -> list[str]:
        return sorted(self.frames)

    def calendar(self) -> pd.DatetimeIndex:
        """Every date on which at least one symbol has a bar, ascending."""
        dates = sorted(set().union(*(set(f.index) for f in self.frames.values())))
        return pd.DatetimeIndex(dates, name="date")

    def fingerprint(self) -> str:
        """A stable digest of the data, so a backtest can name exactly what it ran on."""
        digest = hashlib.sha256()
        for symbol in self.symbols:
            buffer = io.StringIO()
            self.frames[symbol].to_csv(buffer, float_format="%.10g", date_format="%Y-%m-%d")
            digest.update(symbol.encode() + b"\n" + buffer.getvalue().encode())
        return digest.hexdigest()[:16]

    def view(self, as_of) -> PanelView:
        return PanelView(self, pd.Timestamp(as_of).normalize())

    def truncated(self, end) -> PricePanel:
        """A copy holding only bars dated on or before ``end``: later data does not exist in it.

        Used for parameter selection, so a choice made on a training window cannot be
        influenced by anything after it, however the strategy reads its data.
        """
        end = pd.Timestamp(end).normalize()
        frames = {s: f.loc[:end].copy() for s, f in self.frames.items()}
        frames = {s: f for s, f in frames.items() if not f.empty}
        if not frames:
            raise DataError(f"no data on or before {end.date()}")
        return PricePanel(frames, dict(self.dropped_bars), f"{self.source} (to {end.date()})")

    def bar_on(self, symbol: str, date) -> pd.Series | None:
        """The bar dated exactly ``date`` (for the engine's fills), or None."""
        frame = self.frames.get(symbol)
        date = pd.Timestamp(date).normalize()
        if frame is None or date not in frame.index:
            return None
        return frame.loc[date]


class PanelView:
    """The panel as it looked at the close of one date. Nothing later is reachable."""

    def __init__(self, panel: PricePanel, as_of: pd.Timestamp) -> None:
        self._panel = panel
        self._as_of = as_of
        self.max_date_served: pd.Timestamp | None = None

    @property
    def as_of(self) -> pd.Timestamp:
        return self._as_of

    @property
    def symbols(self) -> list[str]:
        return self._panel.symbols

    def _visible(self, symbol: str) -> pd.DataFrame:
        frame = self._panel.frames.get(symbol.upper())
        if frame is None:
            raise KeyError(f"unknown symbol {symbol!r}")
        visible = frame.loc[: self._as_of]
        if not visible.empty:
            last = visible.index[-1]
            if self.max_date_served is None or last > self.max_date_served:
                self.max_date_served = last
        return visible

    def history(self, symbol: str, field: str = "close", lookback: int | None = None) -> pd.Series:
        """``field`` for bars on or before the view's date (a copy), oldest first."""
        if field not in FIELDS:
            raise KeyError(f"unknown field {field!r}")
        series = self._visible(symbol)[field]
        if lookback is not None:
            if lookback < 1:
                raise ValueError("lookback must be positive")
            series = series.iloc[-lookback:]
        return series.copy()

    def bars(self, symbol: str, lookback: int | None = None) -> pd.DataFrame:
        frame = self._visible(symbol)
        return (frame.iloc[-lookback:] if lookback else frame).copy()

    def last_bar(self, symbol: str) -> pd.Series | None:
        frame = self._visible(symbol)
        return None if frame.empty else frame.iloc[-1].copy()

    def has_bar_today(self, symbol: str) -> bool:
        return self._as_of in self._panel.frames.get(symbol.upper(), pd.DataFrame()).index


# ------------------------------------------------------------------------- sources

def load_csv_directory(path: str | Path, symbols: Iterable[str] | None = None, *,
                       on_missing: MissingPolicy = "reject") -> PricePanel:
    """One ``<SYMBOL>.csv`` per symbol (Date, Open, High, Low, Close, Volume): offline and reproducible."""
    directory = Path(path)
    wanted = [s.upper() for s in symbols] if symbols else sorted(p.stem.upper() for p in directory.glob("*.csv"))
    frames = {}
    for symbol in wanted:
        file = directory / f"{symbol}.csv"
        if not file.is_file():
            raise DataError(f"{symbol}: no file {file.name}")
        frames[symbol] = pd.read_csv(file)
    return PricePanel.from_frames(frames, on_missing=on_missing, source=f"csv:{directory.name}")


def load_upstream_yahoo(symbols: Iterable[str], as_of: str, *, on_missing: MissingPolicy = "reject") -> PricePanel:
    """Daily bars through upstream TradingAgents' Yahoo loader (network, cached; about five years).

    Gaps are not filled: a backtest must not trade on invented prices.
    """
    from tradingagents.dataflows.vendors.yahoo.ohlcv import load_ohlcv

    frames = {s.upper(): load_ohlcv(s, as_of, fill_gaps=False) for s in symbols}
    return PricePanel.from_frames(frames, on_missing=on_missing, source="yahoo (adjusted)")
