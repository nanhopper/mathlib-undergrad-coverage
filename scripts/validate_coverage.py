"""Producer-side invariants for the published schema, also callable from CI."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path

from coverage_model import DataError, SCHEMA_VERSION, STATUSES


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DataError(message)


def _summary(value: dict) -> None:
    counts = value["statuses"]
    _require(set(counts) == set(STATUSES), "Invalid evidence status inventory")
    _require(all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in counts.values()),
             "Evidence counts must be nonnegative integers")
    _require(value["total"] == sum(counts.values()), "Catalog total does not reconcile")
    _require(value["covered"] == counts["declaration"] + counts["module"], "Covered count does not reconcile")
    if value["total"]:
        _require(isinstance(value["percentage"], (int, float)) and math.isclose(
            value["percentage"], 100 * value["covered"] / value["total"], abs_tol=1e-9),
            "Coverage percentage does not reconcile")
    else:
        _require(value["percentage"] is None, "An empty catalog must have unavailable coverage")


def _comparison(value: dict, months: int) -> None:
    _require(value["cohort_size"] > 0 and value["excluded"] >= 0, "Invalid comparable cohort")
    for key in ("recent", "prior"):
        rate = value[key]
        _require(rate["net"] == rate["gains"] - rate["losses"], "Cohort net does not reconcile")
        _require(math.isclose(rate["per_month"], rate["net"] / months), "Incorrect calendar-window pace")
        _require(math.isclose(rate["percentage_points"], 100 * rate["net"] / value["cohort_size"]),
                 "Cohort percentage-point change does not reconcile")
    _require(math.isclose(value["pace_change"], value["recent"]["per_month"] - value["prior"]["per_month"]),
             "Pace comparison does not reconcile")


def validate_payload(payload: dict) -> None:
    _require(payload["schema_version"] == SCHEMA_VERSION, "Unsupported coverage schema")
    _require({b["id"] for b in payload["benchmarks"]} == {"named", "undergraduate"}
             and len(payload["benchmarks"]) == 2, "Both distinct coverage benchmarks are required")
    for key in ("observed_at", "generated_at"):
        _require(datetime.fromisoformat(payload["meta"][key]).tzinfo is not None, "Missing timestamp timezone")
    for benchmark in payload["benchmarks"]:
        records = benchmark["records"]
        events = benchmark["events"]
        _require(bool(records) and bool(events), "Empty benchmark evidence")
        states = {}
        counts_by_event = []
        subjects = {s["id"] for s in benchmark["subjects"]}
        for index, event in enumerate(events):
            _require(index == 0 or datetime.fromisoformat(event["at"]) >= datetime.fromisoformat(events[index - 1]["at"]),
                     "Events are not in mainline observation order")
            ids = [change[0] for change in event["changes"]]
            _require(len(set(ids)) == len(ids), "Duplicate identity in an event")
            for identifier, record_index in event["changes"]:
                if record_index is None:
                    _require(identifier in states, "Removal of an absent identity")
                    del states[identifier]
                else:
                    _require(isinstance(record_index, int) and 0 <= record_index < len(records),
                             "Invalid evidence record index")
                    record = records[record_index]
                    _require(record["id"] == identifier and record["subject"] in subjects,
                             "Evidence identity or subject mismatch")
                    _require(record["status"] in STATUSES, "Unknown record status")
                    states[identifier] = record
            summary = {key: 0 for key in STATUSES}
            by_subject = {}
            for record in states.values():
                summary[record["status"]] += 1
                bucket = by_subject.setdefault(record["subject"], dict.fromkeys(STATUSES, 0))
                bucket[record["status"]] += 1
            counts_by_event.append((summary, by_subject))

        previous = None
        for snapshot in [*benchmark["timeline"], benchmark["latest"]]:
            _summary(snapshot["overall"])
            event_index = snapshot["event_index"]
            _require(isinstance(event_index, int) and 0 <= event_index < len(events), "Invalid snapshot event index")
            counts, by_subject = counts_by_event[event_index]
            _require(snapshot["overall"]["statuses"] == counts, "Snapshot does not match its historical evidence")
            _require(set(snapshot["subjects"]) == set(by_subject), "Snapshot subject inventory does not reconcile")
            for subject, value in snapshot["subjects"].items():
                _summary(value)
                _require(value["statuses"] == by_subject[subject], "Subject does not match its evidence")
            if previous is not None:
                flow = snapshot["flow"]
                _require(flow is not None, "A subsequent snapshot must expose its recorded flow")
                _require(flow["net_covered"] == snapshot["overall"]["covered"] - previous["overall"]["covered"],
                         "Recorded covered flow does not reconcile to the observations")
                _require(flow["net_total"] == snapshot["overall"]["total"] - previous["overall"]["total"],
                         "Catalog flow does not reconcile to the observations")
            for months in (3, 6, 12):
                window = snapshot["windows"][str(months)]
                if window["available"]:
                    _comparison(window["overall"], months)
                    for value in window["subjects"].values():
                        _comparison(value, months)
                else:
                    _require(bool(window["reason"]) and window["overall"] is None,
                             "Unavailable comparison must explain its missing data")
            previous = snapshot


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    validate_payload(json.loads(args.path.read_text(encoding="utf-8")))
    print("Coverage artifact is internally consistent.")
