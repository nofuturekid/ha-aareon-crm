"""Statistics building from recorded portal data."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from custom_components.aareon_crm.statistics import (
    MonthValue,
    build_statistics,
    last_complete_month,
    parse_consumption,
)

from .conftest import load

BERLIN = ZoneInfo("Europe/Berlin")


def test_duplicate_portal_rows_are_not_counted_twice():
    """The portal lists 2024-04..07 twice (two meter ids); summing both would overstate."""
    months = parse_consumption(load("consumption_flat.json"))
    heating_2024 = sum(v.amount for p, v in months["heating"].items() if p.startswith("2024"))
    raw = load("consumption_flat.json")["consumptions"]["100"].values()
    naive = sum(
        r["amount"] for r in raw if r["service"] == "HEATING" and r["period"].startswith("2024")
    )
    assert heating_2024 == pytest.approx(5639.5, rel=0.001)
    assert naive > heating_2024 + 100


def test_history_reaches_back_to_2022_for_both_services():
    months = parse_consumption(load("consumption_flat.json"))
    assert min(months["heating"]) == "2022-02"
    assert min(months["hot_water"]) == "2022-02"
    assert set(parse_consumption(load("consumption_workshop.json"))) == {"heating"}


def test_estimated_kept_untracked_and_empty_dropped():
    results = {
        "consumptions": {
            "1": {
                "a": {
                    "service": "HEATING",
                    "period": "2025-01",
                    "amount": 10,
                    "amount_standardized": 5,
                    "estimated": True,
                    "consumption_tracked": True,
                },
                "b": {
                    "service": "HEATING",
                    "period": "2025-02",
                    "amount": 20,
                    "amount_standardized": None,
                    "estimated": False,
                    "consumption_tracked": False,
                },
                "c": {
                    "service": "HEATING",
                    "period": "2025-03",
                    "amount": None,
                    "estimated": False,
                    "consumption_tracked": True,
                },
                "d": {
                    "service": "COLD_WATER",
                    "period": "2025-01",
                    "amount": 1,
                    "estimated": False,
                    "consumption_tracked": True,
                },
            }
        }
    }
    assert parse_consumption(results) == {"heating": {"2025-01": MonthValue(10.0, 5.0, True)}}


def test_flats_of_one_contract_are_added():
    row = {
        "service": "HEATING",
        "period": "2025-01",
        "amount": 10,
        "amount_standardized": 4,
        "estimated": False,
    }
    months = parse_consumption({"consumptions": {"1": {"a": row}, "2": {"a": row}}})
    assert months["heating"]["2025-01"] == MonthValue(20.0, 8.0, False)


def test_sum_is_cumulative_and_start_is_local_midnight():
    months = {
        "heating": {
            "2025-01": MonthValue(100, 90, False),
            "2025-07": MonthValue(0, 50, False),
            "2025-08": MonthValue(25.5, 60, False),
        }
    }
    stats = build_statistics(months, BERLIN)
    rows = stats["heating"]
    assert [r["sum"] for r in rows] == [100, 100, 125.5]
    assert [r["state"] for r in rows] == [100, 0, 25.5]
    # Winter month starts 23:00 UTC the day before, summer month 22:00 UTC.
    assert rows[0]["start"] == datetime(2024, 12, 31, 23, tzinfo=UTC)
    assert rows[1]["start"] == datetime(2025, 6, 30, 22, tzinfo=UTC)
    assert [r["sum"] for r in stats["heating_standardized"]] == [90, 140, 200]


def test_full_fixture_yearly_sums_match_portal():
    stats = build_statistics(parse_consumption(load("consumption_flat.json")), BERLIN)
    rows = stats["heating"]
    by_year: dict[int, float] = {}
    for r in rows:
        by_year[r["start"].astimezone(BERLIN).year] = (
            by_year.get(r["start"].astimezone(BERLIN).year, 0) + r["state"]
        )
    assert by_year[2023] == pytest.approx(5328.7, rel=0.001)
    assert rows[-1]["sum"] == pytest.approx(sum(r["state"] for r in rows))
    assert [r["start"] for r in rows] == sorted(r["start"] for r in rows)


def test_last_complete_month_skips_current_and_falls_back():
    by = {
        "2025-08": MonthValue(1, 1, False),
        "2025-09": MonthValue(2, 2, False),
        "2025-10": MonthValue(3, 3, False),
    }
    assert last_complete_month(by, date(2025, 10, 20))[0] == "2025-09"
    assert (
        last_complete_month({"2025-10": MonthValue(3, 3, False)}, date(2025, 10, 20))[0]
        == "2025-10"
    )
    assert last_complete_month({}, date(2025, 10, 20)) is None
