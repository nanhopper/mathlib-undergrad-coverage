import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  DataValidationError, STATUS_KEYS, benchmarkFor, changesAt, eventsForSubject,
  filterRecords, formatClosedMonths, formatCount, formatDate, formatPercent, formatSigned, observationAge,
  replayRecords, safeHttpUrl, snapshotsFor, sourceFileUrl, subjectRows, validatePayload, windowFor,
} from "../web/dashboard-model.js";

const sha = (letter) => letter.repeat(40);
const observed = "2026-09-08T10:00:00Z";
const flow = (values = {}) => ({
  gains: 0, losses: 0, added: 0, removed: 0, covered_added: 0, covered_removed: 0,
  net_covered: 0, net_total: 0, documentation_gains: 0, source_gains: 0, unknown_gains: 0,
  ...values,
});
const recentFlow = () => flow({ gains: 1, added: 1, removed: 1, net_covered: 1, documentation_gains: 1 });
const partialFlow = () => flow({ losses: 1, added: 1, removed: 1, covered_removed: 1, net_covered: -2 });

function topic(id, label, subject, status, references = [], extra = {}) {
  return {
    id, label, subject, status, references, path: [subject, label], note: "",
    reported_date: null, authors: null, source: "mathlib4", ...extra,
  };
}

function summarize(records) {
  const statuses = Object.fromEntries(STATUS_KEYS.map((status) => [status, records.filter((record) => record.status === status).length]));
  const total = records.length;
  const covered = statuses.declaration + statuses.module;
  return { total, covered, percentage: total ? 100 * covered / total : null, statuses };
}

function comparison(months, cohortSize = 2, recentNet = 1) {
  const rate = (net) => ({
    gains: Math.max(0, net), losses: Math.max(0, -net), net,
    per_month: net / months, percentage_points: 100 * net / cohortSize,
  });
  return { cohort_size: cohortSize, excluded: 2, recent: rate(recentNet), prior: rate(0), pace_change: recentNet / months };
}

function windows(end, available = false) {
  return Object.fromEntries([3, 6, 12].map((months) => {
    const start = months === 3 ? "2026-06-01" : months === 6 ? "2026-03-01" : "2025-09-01";
    const priorStart = months === 3 ? "2026-03-01" : months === 6 ? "2025-09-01" : "2024-09-01";
    const canCompare = available && months !== 12;
    return [String(months), {
      available: canCompare,
      reason: canCompare ? null : "Catalog history does not cover both complete windows.",
      months, start: available ? start : null, end, prior_start: available ? priorStart : null,
      overall: canCompare ? comparison(months) : null,
      subjects: canCompare ? { algebra: comparison(months, 1), analysis: comparison(months, 1, 0) } : {},
      flow: available ? recentFlow() : null,
    }];
  }));
}

function benchmark(id = "named") {
  const records = [
    topic("q1", "Old theorem name", "algebra", "unlinked"),
    topic("q2", "A module-linked topic", "analysis", "module", ["Mathlib/Analysis/Basic.html"]),
    topic("q3", "A reported result", "analysis", "reported", [], { authors: "A. Author", reported_date: "2024" }),
    topic("q1", "Renamed theorem", "algebra", "declaration", ["Theorem.proof"], { note: "A documentation update." }),
    topic("q4", "A statement, not a proof", "analysis", "statement", ["Theorem.statement"]),
    topic("q1", "Latest theorem name", "algebra", "qualified", [], { note: "The source qualifies this entry." }),
    topic("q5", "An external result", "later", "external", ["https://example.org/theorem"]),
  ];
  const event = (at, letter, changes, initial = false, context = "unknown") => ({
    at, committed_at: at, commit: sha(letter), source: "mathlib4",
    url: `https://github.com/leanprover-community/mathlib4/commit/${sha(letter)}`,
    summary: initial ? "Populate the catalog" : "Update catalog evidence",
    context, initial, changes,
  });
  const events = [
    event("2024-12-09T12:00:00Z", "a", [["q1", 0], ["q2", 1], ["q3", 2]], true),
    event("2026-06-12T12:00:00Z", "b", [["q1", 3], ["q3", null], ["q4", 4]], false, "documentation_only"),
    event("2026-09-04T12:00:00Z", "c", [["q1", 5], ["q2", null], ["q5", 6]], false, "source_accompanied"),
  ];
  const snapshot = (asOf, eventIndex, indices, kind, snapshotFlow, comparable = false) => {
    const current = indices.map((index) => records[index]);
    const bySubject = Object.fromEntries([...new Set(current.map((record) => record.subject))]
      .map((subject) => [subject, summarize(current.filter((record) => record.subject === subject))]));
    return {
      date: asOf.slice(0, 10), as_of: asOf, kind, event_index: eventIndex,
      source: events[eventIndex].source, commit: events[eventIndex].commit, commit_date: events[eventIndex].committed_at,
      overall: summarize(current), subjects: bySubject, flow: snapshotFlow,
      windows: windows(comparable ? "2026-09-01" : "2026-03-01", comparable),
    };
  };
  return {
    id, title: id === "named" ? "Named-theorem test catalog" : "Undergraduate test curriculum",
    description: "Synthetic reference catalog for model tests.", scope: "Recorded references only.",
    subjects: [
      { id: "algebra", label: "Algebra" }, { id: "analysis", label: "Analysis" }, { id: "later", label: "Later subject" },
    ],
    records, events,
    timeline: [
      snapshot("2026-03-01T00:00:00Z", 0, [0, 1, 2], "monthly", null),
      snapshot("2026-09-01T00:00:00Z", 1, [3, 1, 4], "monthly", recentFlow(), true),
    ],
    latest: snapshot(observed, 2, [5, 4, 6], "latest", partialFlow(), true),
    diagnostics: { warnings: ["Synthetic data, not a claim about mathlib."], taxonomy: { revision: sha("d") } },
  };
}

function fixture() {
  return {
    schema_version: 2,
    meta: {
      observed_at: observed, generated_at: "2026-09-08T10:02:00Z",
      sources: [{
        name: "mathlib4", url: "https://github.com/leanprover-community/mathlib4.git",
        ref: "master", head: sha("e"), head_date: "2026-09-08T00:00:00Z",
      }],
    },
    benchmarks: [benchmark(), benchmark("undergraduate")],
  };
}

function rejectsMutation(mutate, pattern) {
  const data = fixture();
  mutate(data, data.benchmarks[0]);
  assert.throws(() => validatePayload(data), pattern ?? DataValidationError);
}

test("validates both benchmarks without mutating the payload", () => {
  const data = fixture();
  const before = structuredClone(data);
  assert.equal(validatePayload(data), data);
  assert.deepEqual(data, before);
  assert.equal(benchmarkFor(data, "named").id, "named");
  assert.throws(() => benchmarkFor(data, "unknown"), /Unknown benchmark/);
});

test("rejects empty, old-schema, and malformed payloads", () => {
  for (const value of [null, [], {}, "", { schema_version: 1 }, { schema_version: 2, meta: {} }]) {
    assert.throws(() => validatePayload(value), DataValidationError);
  }
  rejectsMutation((data) => { data.schema_version = "2"; }, /schema/);
  rejectsMutation((data) => { data.benchmarks = []; }, /nonempty/);
});

test("requires exactly the named and undergraduate IDs without duplicates", () => {
  rejectsMutation((data) => { data.benchmarks.pop(); }, /distinct benchmarks/);
  rejectsMutation((data) => { data.benchmarks[1].id = "named"; }, /distinct benchmarks/);
  rejectsMutation((data) => { data.benchmarks[1].id = "activity"; }, /distinct benchmarks/);
  rejectsMutation((data) => { data.benchmarks.push(benchmark()); }, /distinct benchmarks/);
});

test("requires unique subject and source IDs, but allows historical record versions", () => {
  rejectsMutation((data, item) => { item.subjects.push({ ...item.subjects[0] }); }, /duplicate subject/);
  rejectsMutation((data) => { data.meta.sources.push({ ...data.meta.sources[0] }); }, /Duplicate source/);
  const data = fixture();
  assert.equal(data.benchmarks[0].records.filter((record) => record.id === "q1").length, 3);
  assert.doesNotThrow(() => validatePayload(data));
});

for (const key of ["subjects", "records", "events"]) {
  test(`rejects an empty benchmark ${key} array`, () => {
    rejectsMutation((data, item) => { item[key] = []; }, /nonempty/);
  });
}

test("rejects missing record fields, identities, subjects, statuses, and covered references", () => {
  rejectsMutation((data, item) => { item.records[0].id = ""; }, /record id/);
  rejectsMutation((data, item) => { item.records[0].subject = "missing"; }, /unknown subject/);
  rejectsMutation((data, item) => { item.records[0].status = "implemented"; }, /unknown evidence status/);
  rejectsMutation((data, item) => { item.records[1].references = []; }, /lacks a reference/);
  rejectsMutation((data, item) => { delete item.records[0].note; }, /record note/);
  rejectsMutation((data, item) => { delete item.records[0].authors; }, /record authors/);
  rejectsMutation((data, item) => { item.records[0].references = [4]; }, /reference/);
  rejectsMutation((data, item) => { item.records[0].path = [null]; }, /path part/);
});

for (const [name, mutate] of [
  ["negative", (summary) => { summary.statuses.unlinked = -1; }],
  ["fractional", (summary) => { summary.total = 3.5; }],
  ["unsafe integer", (summary) => { summary.total = Number.MAX_SAFE_INTEGER + 1; }],
  ["boolean", (summary) => { summary.covered = true; }],
  ["nonfinite", (summary) => { summary.percentage = Infinity; }],
  ["missing status", (summary) => { delete summary.statuses.statement; }],
  ["extra status", (summary) => { summary.statuses.unknown = 0; }],
  ["incorrect covered", (summary) => { summary.covered = 2; }],
  ["incorrect total", (summary) => { summary.total = 5; }],
  ["incorrect percentage", (summary) => { summary.percentage = 99; }],
  ["unavailable nonempty percentage", (summary) => { summary.percentage = null; }],
]) {
  test(`rejects ${name} summary counts`, () => {
    rejectsMutation((data, item) => mutate(item.timeline[0].overall));
  });
}

test("rejects success-shaped empty observations and wrong historical summaries", () => {
  rejectsMutation((data, item) => {
    item.timeline[0].overall = summarize([]);
  }, /empty snapshot/);
  rejectsMutation((data, item) => {
    item.timeline[0].overall = summarize([item.records[3], item.records[1], item.records[4]]);
  }, /replayed evidence/);
  rejectsMutation((data, item) => {
    item.events[0].changes = [];
  }, /empty catalog/);
});

test("subject inventories must reconcile to exact historical records", () => {
  rejectsMutation((data, item) => { delete item.timeline[0].subjects.analysis; }, /snapshot subjects/);
  rejectsMutation((data, item) => { item.timeline[0].subjects.later = summarize([]); }, /snapshot subjects/);
  rejectsMutation((data, item) => {
    item.timeline[0].subjects.algebra = summarize([item.records[3]]);
  }, /subject counts/);
});

test("checks event record bounds, identity matches, source matches, and removals", () => {
  rejectsMutation((data, item) => { item.events[0].changes[0][1] = 500; }, /missing record/);
  rejectsMutation((data, item) => { item.events[0].changes[0][1] = -1; }, /record index/);
  rejectsMutation((data, item) => { item.events[0].changes[0][1] = 0.5; }, /record index/);
  rejectsMutation((data, item) => { item.events[0].changes[0][1] = "0"; }, /record index/);
  rejectsMutation((data, item) => { item.events[0].changes[0][0] = "wrong"; }, /identity\/source mismatch/);
  rejectsMutation((data, item) => { item.events[0].changes.push(["q1", 0]); }, /repeats topic/);
  rejectsMutation((data, item) => { item.events[0].changes.push(["absent", null]); }, /removes an absent/);
  rejectsMutation((data, item) => { item.events[0].changes[0].push(1); }, /malformed change/);
  rejectsMutation((data, item) => { item.records[0].source = "mathlib3"; }, /unknown source/);
});

test("checks event order, initialization markers, revision provenance, and snapshot indices", () => {
  rejectsMutation((data, item) => { item.events[1].at = "2024-01-01T00:00:00Z"; }, /observation order/);
  rejectsMutation((data, item) => { item.events[1].initial = true; }, /initial catalog event/);
  rejectsMutation((data, item) => { item.events[0].commit = "abc"; }, /source revision/);
  rejectsMutation((data, item) => { item.events[1].context = "proof_completed"; }, /commit context/);
  rejectsMutation((data, item) => { item.latest.event_index = 99; }, /missing event/);
  rejectsMutation((data, item) => { item.latest.event_index = 1; }, /evidence at its cutoff/);
  rejectsMutation((data, item) => { item.latest.commit = sha("f"); }, /source does not match/);
});

test("monthly cutoffs exclude boundary events while latest includes its exact instant", () => {
  const data = fixture();
  const boundary = "2026-09-01T00:00:00Z";
  data.meta.observed_at = boundary;
  for (const item of data.benchmarks) {
    item.events.pop();
    item.events[1].at = boundary;
    item.events[1].committed_at = boundary;
    const monthly = item.timeline[1];
    monthly.event_index = 0;
    monthly.commit = item.events[0].commit;
    monthly.commit_date = item.events[0].committed_at;
    monthly.overall = structuredClone(item.timeline[0].overall);
    monthly.subjects = structuredClone(item.timeline[0].subjects);
    monthly.flow = flow();
    for (const months of [3, 6]) {
      const window = monthly.windows[String(months)];
      window.overall = comparison(months, 3, 0);
      window.overall.excluded = 0;
      window.subjects = { algebra: comparison(months, 1, 0), analysis: comparison(months, 2, 0) };
      window.flow = flow();
    }
    monthly.windows["12"].flow = null;
    item.latest = {
      ...structuredClone(monthly), date: "2026-09-01", as_of: boundary, kind: "latest",
      event_index: 1, commit: item.events[1].commit, commit_date: boundary,
      overall: summarize([item.records[3], item.records[1], item.records[4]]),
      subjects: {
        algebra: summarize([item.records[3]]),
        analysis: summarize([item.records[1], item.records[4]]),
      },
      flow: recentFlow(),
    };
  }
  assert.doesNotThrow(() => validatePayload(data));
  const item = data.benchmarks[0];
  assert.equal(replayRecords(item, item.timeline[1].event_index).find((record) => record.id === "q1").label, "Old theorem name");
  assert.equal(replayRecords(item, item.latest.event_index).find((record) => record.id === "q1").label, "Renamed theorem");
  item.timeline[1].event_index = 1;
  assert.throws(() => validatePayload(data), /evidence at its cutoff/);
});

test("checks timestamps, calendar dates, and matching observation metadata", () => {
  rejectsMutation((data) => { data.meta.observed_at = "2026-09-08T10:00:00"; }, /timezone/);
  rejectsMutation((data) => { data.meta.generated_at = "2026-09-01T00:00:00Z"; }, /Generation predates/);
  rejectsMutation((data, item) => { item.latest.date = "2026-02-30"; }, /valid date/);
  rejectsMutation((data, item) => { item.latest.as_of = "2026-09-08T11:00:00Z"; }, /after the dataset/);
  rejectsMutation((data, item) => { item.timeline[0].kind = "latest"; }, /invalid kind/);
  rejectsMutation((data, item) => { item.timeline.reverse(); }, /chronological|flow/);
});

test("checks reconciled flows, gain contexts, and changes between snapshot levels", () => {
  rejectsMutation((data, item) => { item.latest.flow.net_covered = 0; }, /net_covered/);
  rejectsMutation((data, item) => { item.latest.flow.net_total = 2; }, /net_total/);
  rejectsMutation((data, item) => { item.latest.flow.covered_added = 2; }, /impossible covered catalog/);
  rejectsMutation((data, item) => { item.timeline[1].flow.documentation_gains = 0; }, /gain contexts/);
  rejectsMutation((data, item) => { item.latest.flow = flow(); }, /level change/);
  rejectsMutation((data, item) => { item.latest.flow = null; }, /level change/);
});

test("checks available and unavailable comparison shapes and rate arithmetic", () => {
  rejectsMutation((data, item) => { item.latest.windows["6"].overall.cohort_size = 0; }, /cohort_size/);
  rejectsMutation((data, item) => { item.latest.windows["6"].overall.recent.per_month = 1; }, /per_month/);
  rejectsMutation((data, item) => { item.latest.windows["6"].overall.prior.net = 1; }, /prior.net/);
  rejectsMutation((data, item) => { item.latest.windows["6"].overall.pace_change = 5; }, /pace_change/);
  rejectsMutation((data, item) => { item.latest.windows["12"].reason = null; }, /reason/);
  rejectsMutation((data, item) => { item.latest.windows["12"].overall = comparison(12); }, /unavailable comparisons/);
  rejectsMutation((data, item) => { item.latest.windows["6"].subjects.missing = comparison(6); }, /unknown subject/);
  rejectsMutation((data, item) => { delete item.latest.windows["3"]; }, /missing or unexpected keys/);
  rejectsMutation((data, item) => { item.latest.windows["6"].end = "2026-10-01"; }, /after its observation/);
});

test("requires safe mandatory source/event URLs but preserves remote text as text", () => {
  rejectsMutation((data) => { data.meta.sources[0].url = "javascript:alert(1)"; }, /safe HTTP/);
  rejectsMutation((data, item) => { item.events[1].url = "data:text/html,unsafe"; }, /safe HTTP/);
  const data = fixture();
  data.benchmarks[0].records[0].label = '<img src=x onerror="alert(1)">';
  data.benchmarks[0].records[0].references = ["javascript:alert(1)"];
  assert.doesNotThrow(() => validatePayload(data));
  assert.equal(replayRecords(data.benchmarks[0], 0)[0].label, '<img src=x onerror="alert(1)">');
  assert.equal(safeHttpUrl(data.benchmarks[0].records[0].references[0]), null);
});

test("replay removes entries and never substitutes latest names or references", () => {
  const item = fixture().benchmarks[0];
  const original = structuredClone(item);
  const oldest = replayRecords(item, 0);
  const middle = replayRecords(item, 1);
  const latest = replayRecords(item, 2);
  assert.equal(oldest.find((record) => record.id === "q1").label, "Old theorem name");
  assert.deepEqual(oldest.find((record) => record.id === "q1").references, []);
  assert.equal(middle.find((record) => record.id === "q1").label, "Renamed theorem");
  assert.deepEqual(middle.find((record) => record.id === "q1").references, ["Theorem.proof"]);
  assert.equal(latest.find((record) => record.id === "q1").label, "Latest theorem name");
  assert.ok(oldest.some((record) => record.id === "q3"));
  assert.ok(!middle.some((record) => record.id === "q3"));
  assert.ok(!latest.some((record) => record.id === "q2"));
  assert.deepEqual(item, original);
  assert.deepEqual(replayRecords(item, -1), []);
  assert.throws(() => replayRecords(item, 3), /outside/);
  assert.throws(() => replayRecords(item, 1.5), /integer/);
});

test("reported dates preserve their original precision and multiple-date wording", () => {
  for (const reportedDate of ["2024", "2024-03", "2024-03-12", "2019, 2021", "2021, 2025", "2024/03"]) {
    const data = fixture();
    const item = data.benchmarks[0];
    item.records[2].reported_date = reportedDate;
    assert.doesNotThrow(() => validatePayload(data));
    assert.equal(replayRecords(item, 0).find((record) => record.id === "q3").reported_date, reportedDate);
    assert.equal(changesAt(item, 1).find((change) => change.id === "q3").before.reported_date, reportedDate);
  }
});

test("event evidence distinguishes initialization, reference changes, and catalog edits", () => {
  const item = fixture().benchmarks[0];
  assert.ok(changesAt(item, 0).every((change) => change.kind === "baseline" && change.before === null));
  assert.deepEqual(changesAt(item, 1).map((change) => [change.id, change.kind]), [["q1", "gain"], ["q3", "removal"], ["q4", "addition"]]);
  assert.deepEqual(changesAt(item, 2).map((change) => change.kind), ["loss", "removal", "addition"]);
  assert.equal(changesAt(item, 1)[1].before.reported_date, "2024");
  item.records[5].status = "declaration";
  item.records[5].references = ["Theorem.new_reference"];
  assert.equal(changesAt(item, 2)[0].kind, "edit", "a rename/reference edit is not a coverage gain");
  assert.throws(() => changesAt(item, -1), /outside/);
});

test("subject event filtering retains removals and observes the selected cutoff", () => {
  const item = fixture().benchmarks[0];
  assert.deepEqual(eventsForSubject(item, 1, "analysis").map((entry) => entry.index), [0, 1]);
  assert.deepEqual(eventsForSubject(item, 2, "analysis").map((entry) => entry.index), [0, 1, 2]);
  assert.deepEqual(eventsForSubject(item, 1, "later"), []);
  assert.deepEqual(eventsForSubject(item, 2, "later").map((entry) => entry.index), [2]);
  assert.throws(() => eventsForSubject(item, 10), /outside/);
});

test("subject sorting defaults to gaps and places unavailable data after real values", () => {
  const item = fixture().benchmarks[0];
  const snapshot = item.timeline[1];
  const window = windowFor(snapshot);
  const rows = subjectRows(item, snapshot, window);
  assert.deepEqual(rows.map((row) => row.id), ["analysis", "algebra", "later"]);
  assert.equal(rows[0].remaining, 1);
  assert.equal(rows[1].remaining, 0);
  assert.equal(rows[2].remaining, null);
  assert.equal(rows[2].percentage, null);
  assert.equal(rows[2].summary, null);
  assert.deepEqual(subjectRows(item, snapshot, window, { sort: "coverage" }).map((row) => row.id), ["analysis", "algebra", "later"]);
  assert.deepEqual(subjectRows(item, snapshot, window, { sort: "change" }).map((row) => row.id), ["algebra", "analysis", "later"]);
  assert.equal(rows.find((row) => row.id === "analysis").change, 0, "known zero must stay distinct from unavailable");
});

test("subject search matches labels and stable IDs without inventing missing comparisons", () => {
  const item = fixture().benchmarks[0];
  const snapshot = item.timeline[1];
  const window = windowFor(snapshot);
  assert.deepEqual(subjectRows(item, snapshot, window, { query: " ALGEBRA " }).map((row) => row.id), ["algebra"]);
  assert.equal(subjectRows(item, snapshot, window, { query: "absent label" }).length, 0);
  const unavailable = subjectRows(item, snapshot, windowFor(snapshot, 12));
  assert.ok(unavailable.every((row) => row.comparison === null && row.change === null));
  delete window.subjects.analysis;
  assert.equal(subjectRows(item, snapshot, window).find((row) => row.id === "analysis").change, null);
});

test("evidence filters preserve the distinction between references, statements, and reports", () => {
  const item = fixture().benchmarks[0];
  const oldest = replayRecords(item, 0);
  const middle = replayRecords(item, 1);
  assert.deepEqual(filterRecords(oldest, { status: "covered" }).map((record) => record.id), ["q2"]);
  assert.deepEqual(filterRecords(oldest, { status: "reported" }).map((record) => record.id), ["q3"]);
  assert.deepEqual(filterRecords(middle, { status: "statement" }).map((record) => record.id), ["q4"]);
  assert.equal(filterRecords(middle, { status: "covered" }).length, 2);
  assert.equal(filterRecords(middle, { status: "not-covered" }).length, 1);
  assert.deepEqual(filterRecords(middle, { subject: "algebra", query: "DOCUMENTATION" }).map((record) => record.id), ["q1"]);
  assert.deepEqual(filterRecords(oldest, { query: "analysis/basic.html" }).map((record) => record.id), ["q2"]);
  assert.deepEqual(filterRecords(oldest, { query: "A. Author" }).map((record) => record.id), ["q3"]);
  assert.deepEqual(filterRecords(middle, { subject: "later" }), []);
});

test("a subject named all is a real identity, not the all-subjects control", () => {
  const records = [topic("q1", "First entry", "all", "unlinked"), topic("q2", "Second entry", "other", "unlinked")];
  assert.equal(filterRecords(records).length, 2);
  assert.deepEqual(filterRecords(records, { subject: "all" }).map((record) => record.id), ["q1"]);
});

test("window selection uses the explicit closed period, not the partial latest date", () => {
  const item = fixture().benchmarks[0];
  assert.equal(snapshotsFor(item).at(-1), item.latest);
  assert.equal(snapshotsFor(item)[0], item.timeline[0]);
  assert.equal(windowFor(item.latest), item.latest.windows["6"]);
  assert.equal(windowFor(item.latest).end, "2026-09-01");
  assert.notEqual(windowFor(item.latest).end, item.latest.date);
  assert.equal(windowFor(item.latest, 3).start, "2026-06-01");
  assert.equal(windowFor(item.latest, "6").prior_start, "2025-09-01");
  assert.equal(windowFor(item.latest, 12).available, false);
  assert.equal(windowFor(item.latest, 12).overall, null);
  assert.notEqual(windowFor(item.latest, 12).flow, null, "full-catalog flow can exist without paired-window history");
  assert.throws(() => windowFor(item.latest, 9), /3-, 6-, or 12-month/);
});

test("historical exclusions are preserved rather than derived from the selected catalog size", () => {
  const data = validatePayload(fixture());
  const snapshot = data.benchmarks[0].latest;
  const comparison = windowFor(snapshot).overall;
  assert.equal(comparison.cohort_size, 2);
  assert.equal(comparison.excluded, 2);
  assert.equal(snapshot.overall.total, 3);
  assert.notEqual(comparison.excluded, snapshot.overall.total - comparison.cohort_size);
});

test("a recent catalog can have latest evidence without closed monthly observations", () => {
  const data = fixture();
  for (const item of data.benchmarks) {
    item.timeline = [];
    item.latest.flow = null;
  }
  assert.doesNotThrow(() => validatePayload(data));
  assert.equal(snapshotsFor(data.benchmarks[0]).length, 1);
});

test("HTTP links are allowed without guessing declaration or module destinations", () => {
  assert.equal(safeHttpUrl("https://example.org/theorem?q=1#proof"), "https://example.org/theorem?q=1#proof");
  assert.equal(safeHttpUrl(" HTTP://example.org "), "http://example.org/");
  for (const value of [
    null, {}, "", "javascript:alert(1)", "data:text/html,anything", "file:///C:/secret", "ftp://example.org",
    "//example.org", "Mathlib/Analysis/Basic.html", "Theorem.proof", "https://", "http:example.org",
    "https://name:password@example.org", "https://example.org\\@evil.org", "java\nscript:alert(1)", "https://exa\nmple.org",
  ]) assert.equal(safeHttpUrl(value), null, `must not create a link for ${String(value)}`);
});

test("YAML provenance is pinned to the requested benchmark, era, and full revision", () => {
  const observation = { source: "mathlib4", commit: sha("a") };
  assert.equal(sourceFileUrl("named", observation), `https://github.com/leanprover-community/mathlib4/blob/${sha("a")}/docs/1000.yaml`);
  assert.equal(sourceFileUrl("undergraduate", { ...observation, source: "mathlib3" }),
    `https://github.com/leanprover-community/mathlib/blob/${sha("a")}/docs/undergrad.yaml`);
  assert.equal(sourceFileUrl("unknown", observation), null);
  assert.equal(sourceFileUrl("named", { ...observation, source: "__proto__" }), null);
  assert.equal(sourceFileUrl("named", { ...observation, commit: "../master" }), null);
});

test("formatting keeps unavailable distinct from zero and uses UTC dates", () => {
  assert.equal(formatCount(null), "Unavailable");
  assert.equal(formatCount(0), "0");
  assert.equal(formatCount(1234), "1,234");
  assert.equal(formatPercent(null), "Unavailable");
  assert.equal(formatPercent(0), "0.0%");
  assert.equal(formatPercent(100 * 399 / 566), "70.5%");
  assert.equal(formatSigned(0, 2), "0.00");
  assert.equal(formatSigned(1 / 6, 2), "+0.17");
  assert.equal(formatSigned(-2), "-2");
  assert.equal(formatDate("2026-01-01T00:30:00+02:00"), "31 Dec 2025");
});

test("closed-month labels use exclusive window boundaries, including year and leap-day rollovers", () => {
  assert.equal(formatClosedMonths("2026-03-01", "2026-09-01"), "Mar 2026 – Aug 2026");
  assert.equal(formatClosedMonths("2025-09-01", "2026-03-01"), "Sept 2025 – Feb 2026");
  assert.equal(formatClosedMonths("2023-12-01", "2024-03-01"), "Dec 2023 – Feb 2024");
  assert.equal(formatClosedMonths(null, "2026-09-01"), "Unavailable");
  assert.throws(() => formatClosedMonths("2026-09-01", "2026-09-01"), /end after/);
  const latest = fixture().benchmarks[0].latest;
  assert.equal(formatClosedMonths(windowFor(latest).start, windowFor(latest).end), "Mar 2026 – Aug 2026");
});

test("compact periods omit repeated years without hiding cross-year or unavailable boundaries", () => {
  const compact = { compact: true };
  assert.equal(formatClosedMonths("2026-03-01", "2026-09-01", compact), "Mar–Aug 2026");
  assert.equal(formatClosedMonths("2025-09-01", "2026-03-01", compact), "Sept 2025 – Feb 2026");
  assert.equal(formatClosedMonths("2025-10-01", "2026-01-01", compact), "Oct–Dec 2025");
  assert.equal(formatClosedMonths("2024-02-01", "2024-03-01", compact), "Feb 2024");
  assert.equal(formatClosedMonths(null, "2026-09-01", compact), "Unavailable");
  assert.throws(() => formatClosedMonths("2026-09-01", "2026-03-01", compact), /end after/);
});

test("initial markup leads with controls and subjects, with research tools closed", () => {
  const html = readFileSync(new URL("../web/index.html", import.meta.url), "utf8");
  const element = (tag, id) => {
    const found = [...html.matchAll(new RegExp(`<${tag}\\b[^>]*>`, "g"))]
      .find(([opening]) => opening.includes(`id="${id}"`));
    assert.ok(found, `${id} must be a ${tag} element`);
    return found;
  };
  const explorer = element("section", "explorer");
  const subjects = element("section", "subjects-section");
  const analysis = element("details", "analysis-section");
  const evidence = element("details", "evidence-section");
  const commits = element("details", "events-section");
  assert.ok(explorer.index < subjects.index);
  assert.ok(subjects.index < analysis.index);
  assert.ok(analysis.index < evidence.index);
  for (const [opening] of [analysis, evidence, commits]) {
    assert.doesNotMatch(opening, /\sopen\b/, "research workspaces must start closed");
  }
});

test("observation-age context is explicit, including old and future observations", () => {
  const clock = Date.parse(observed);
  assert.deepEqual(observationAge(observed, clock), { stale: false, label: "Observed less than a day ago" });
  assert.deepEqual(observationAge("2026-09-01T10:00:00Z", clock), { stale: true, label: "Observation is 7 days old" });
  assert.deepEqual(observationAge("2026-09-07T10:00:00Z", clock), { stale: false, label: "Observation is 1 day old" });
  assert.equal(observationAge("2026-09-20T10:00:00Z", clock).stale, true);
});
