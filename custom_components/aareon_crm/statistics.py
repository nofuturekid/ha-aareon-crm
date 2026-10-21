"""Pure helpers: portal consumption JSON -> monthly values -> long-term statistics."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from typing import Any

from homeassistant.components.recorder.models import StatisticData

from .const import SERVICE_KEYS


@dataclass(frozen=True)
class MonthValue:
    """One month of one service."""

    amount: float
    standardized: float | None
    estimated: bool


# service key ("heating") -> period ("2024-04") -> value
Months = dict[str, dict[str, MonthValue]]


def parse_consumption(results: dict[str, Any]) -> Months:
    """Reduce the portal's `results` payload to one value per service and month.

    * Rows the portal marks as not tracked, or without an amount, are dropped.
    * The portal sometimes lists a month twice for one flat (two meter ids,
      identical values); only the first row per (flat, service, period) is kept.
    * Values of several flats under one contract are added up.
    * Estimated rows are kept and flagged: they are the portal's own figure.
    """
    months: dict[str, dict[str, MonthValue]] = defaultdict(dict)
    for rows in (results.get("consumptions") or {}).values():
        seen: set[tuple[str, str]] = set()
        flat: dict[tuple[str, str], MonthValue] = {}
        for row in rows.values() if isinstance(rows, dict) else rows:
            service = SERVICE_KEYS.get(row.get("service"))
            period = row.get("period")
            amount = row.get("amount")
            if (
                service is None
                or not period
                or amount is None
                or not row.get("consumption_tracked", True)
                or (service, period) in seen
            ):
                continue
            seen.add((service, period))
            std = row.get("amount_standardized")
            flat[(service, period)] = MonthValue(
                float(amount),
                None if std is None else float(std),
                bool(row.get("estimated")),
            )
        for (service, period), value in flat.items():
            known = months[service].get(period)
            months[service][period] = (
                value
                if known is None
                else MonthValue(
                    known.amount + value.amount,
                    None
                    if known.standardized is None or value.standardized is None
                    else known.standardized + value.standardized,
                    known.estimated or value.estimated,
                )
            )
    return dict(months)


def _month_start(period: str, tz: tzinfo) -> datetime:
    year, month = (int(p) for p in period.split("-"))
    return datetime(year, month, 1, tzinfo=tz)


def build_statistics(months: Months, tz: tzinfo) -> dict[str, list[StatisticData]]:
    """Build cumulative statistics, keyed by suffix (`heating`, `heating_standardized`).

    One row per month at the month's first local hour; `state` is the monthly
    amount and `sum` the running total. Months missing in the portal are simply
    absent (the sum carries over).
    """
    out: dict[str, list[StatisticData]] = {}
    for service, by_period in months.items():
        for suffix, getter in (
            (service, lambda v: v.amount),
            (f"{service}_standardized", lambda v: v.standardized),
        ):
            total = 0.0
            rows: list[StatisticData] = []
            for period in sorted(by_period):
                value = getter(by_period[period])
                if value is None:
                    continue
                total += value
                rows.append(
                    StatisticData(
                        start=_month_start(period, tz),
                        state=value,
                        sum=round(total, 6),
                    )
                )
            if rows:
                out[suffix] = rows
    return out


def last_complete_month(
    by_period: dict[str, MonthValue], today: date
) -> tuple[str, MonthValue] | None:
    """Latest month before the current one, else the latest available."""
    if not by_period:
        return None
    current = f"{today.year:04d}-{today.month:02d}"
    complete = [p for p in by_period if p < current]
    period = max(complete) if complete else max(by_period)
    return period, by_period[period]
