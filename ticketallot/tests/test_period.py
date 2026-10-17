# Self-check for the allotment period logic. Run: python test_period.py
import sys, types
from datetime import datetime, timezone
from unittest.mock import MagicMock

# stub the modmail-only `core` package; everything else is the real file
for name in ("core", "core.checks", "core.models", "core.paginator", "core.time"):
    sys.modules[name] = MagicMock()
sys.modules["core.models"].getLogger = lambda n: MagicMock()

import ticketallot as t

def make(period, now):
    t.utcnow = lambda: now
    o = object.__new__(t.TicketAllot)
    o.alloc_period = period
    o.assignments = {
        # member 1: one per boundary day around Oct 2026 (week 2026-W42 = Oct 12-18)
        "a": {"member_id": 1, "assigned_at": "2026-09-30T23:59:59+00:00"},
        "b": {"member_id": 1, "assigned_at": "2026-10-01T00:00:00+00:00"},
        "c": {"member_id": 1, "assigned_at": "2026-10-11T23:59:59+00:00"},
        "d": {"member_id": 1, "assigned_at": "2026-10-12T00:00:00+00:00"},
        "e": {"member_id": 1, "assigned_at": "2026-10-18T23:59:59+00:00"},
        "f": {"member_id": 1, "assigned_at": "2026-10-31T23:59:59+00:00"},
        "g": {"member_id": 1, "assigned_at": "2026-11-01T00:00:00+00:00"},
        "h": {"member_id": 2, "assigned_at": "2026-10-20T00:00:00+00:00"},
    }
    return o

now = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)  # Saturday, ISO week 42
assert make("all", now)._member_total_count(1) == 7
assert make("month", now)._member_total_count(1) == 5          # b..f
assert make("week", now)._member_total_count(1) == 2           # d, e
assert make("month", now)._member_total_count(1, all_time=True) == 7
assert len(make("month", now)._period_assignments()) == 6      # b..f + h
assert make("week", now)._period_label() == "2026-W42"
assert make("month", now)._period_label() == "2026-10"
# 30-day month: "-31" upper bound must not leak into next month
apr = datetime(2026, 4, 15, tzinfo=timezone.utc)
o = make("month", apr); o.assignments = {"x": {"member_id": 1, "assigned_at": "2026-05-01T00:00:00+00:00"},
                                          "y": {"member_id": 1, "assigned_at": "2026-04-30T23:00:00+00:00"}}
assert o._member_total_count(1) == 1
# ISO week crossing a year: 2026-12-31 is Thursday, week 53 (Dec 28 - Jan 3)
ny = datetime(2026, 12, 31, tzinfo=timezone.utc)
o = make("week", ny); o.assignments = {"x": {"member_id": 1, "assigned_at": "2027-01-03T10:00:00+00:00"},
                                        "y": {"member_id": 1, "assigned_at": "2027-01-04T10:00:00+00:00"}}
assert o._period_label() == "2026-W53" and o._member_total_count(1) == 1
print("ALL CHECKS PASSED")
