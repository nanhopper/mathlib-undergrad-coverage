export const SCHEMA_VERSION = 2;
export const BENCHMARK_IDS = Object.freeze(["named", "undergraduate"]);
export const WINDOW_MONTHS = Object.freeze([3, 6, 12]);
export const STATUS_INFO = Object.freeze({
  declaration: { label: "Declaration reference", description: "A declaration is recorded in the mathlib repository. Counted as covered." },
  module: { label: "Module reference", description: "An internal module reference is recorded. Counted as covered." },
  external: { label: "External reference only", description: "An outside reference, not a recorded mathlib-repository reference." },
  unlinked: { label: "No recorded reference", description: "No repository reference is recorded. This does not establish absence from mathlib." },
  reported: { label: "Reported elsewhere / unlocated", description: "A formalization is reported, without a located mathlib-repository reference." },
  statement: { label: "Statement only", description: "A statement is recorded, not a referenced proof. Not counted as covered." },
  qualified: { label: "Qualified / ambiguous", description: "A partial, qualified, or ambiguous record. Not counted as covered." },
});
export const STATUS_KEYS = Object.freeze(Object.keys(STATUS_INFO));

const REPOSITORIES = Object.freeze({
  mathlib3: "https://github.com/leanprover-community/mathlib",
  mathlib4: "https://github.com/leanprover-community/mathlib4",
});
const SOURCE_FILES = Object.freeze({ named: "docs/1000.yaml", undergraduate: "docs/undergrad.yaml" });
const SHA = /^[a-f0-9]{40}$/i;
const has = (object, key) => Object.hasOwn(object, key);
const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const covered = (record) => record?.status === "declaration" || record?.status === "module";

export class DataValidationError extends Error {
  constructor(message) {
    super(message);
    this.name = "DataValidationError";
  }
}

function requireValue(condition, message) {
  if (!condition) throw new DataValidationError(message);
}

function object(value, path) {
  requireValue(isObject(value), `${path} must be an object.`);
}

function text(value, path, allowEmpty = false) {
  requireValue(typeof value === "string" && (allowEmpty || value.trim().length > 0), `${path} must be text.`);
}

function integer(value, path, minimum = 0) {
  requireValue(Number.isSafeInteger(value) && value >= minimum, `${path} must be an integer of at least ${minimum}.`);
}

function numeric(value, path) {
  requireValue(typeof value === "number" && Number.isFinite(value), `${path} must be a finite number.`);
}

function close(actual, expected, path) {
  numeric(actual, path);
  requireValue(Math.abs(actual - expected) <= 1e-8 * Math.max(1, Math.abs(expected)), `${path} does not reconcile with its counts.`);
}

function date(value, path) {
  requireValue(typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value), `${path} must be a calendar date.`);
  const parsed = new Date(`${value}T00:00:00Z`);
  requireValue(Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value, `${path} is not a valid date.`);
}

function timestamp(value, path) {
  requireValue(typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)
    && Number.isFinite(Date.parse(value)), `${path} must be an ISO timestamp with a timezone.`);
  date(value.slice(0, 10), path);
}

function array(value, path, nonempty = false) {
  requireValue(Array.isArray(value) && (!nonempty || value.length > 0), `${path} must be ${nonempty ? "a nonempty" : "an"} array.`);
}

function sameKeys(value, keys, path) {
  object(value, path);
  requireValue(Object.keys(value).length === keys.length && keys.every((key) => has(value, key)), `${path} has missing or unexpected keys.`);
}

export function safeHttpUrl(value) {
  if (typeof value !== "string") return null;
  const input = value.trim();
  if (!/^https?:\/\//i.test(input) || /[\u0000-\u0020\u007f\\]/u.test(input)) return null;
  try {
    const url = new URL(input);
    return ["http:", "https:"].includes(url.protocol) && url.hostname && !url.username && !url.password ? url.href : null;
  } catch {
    return null;
  }
}

export function sourceFileUrl(benchmarkId, observation) {
  if (!has(SOURCE_FILES, benchmarkId) || !isObject(observation)
      || !has(REPOSITORIES, observation.source) || !SHA.test(observation.commit)) return null;
  return `${REPOSITORIES[observation.source]}/blob/${observation.commit}/${SOURCE_FILES[benchmarkId]}`;
}

function validateSummary(summary, path) {
  object(summary, path);
  sameKeys(summary.statuses, STATUS_KEYS, `${path}.statuses`);
  STATUS_KEYS.forEach((key) => integer(summary.statuses[key], `${path}.statuses.${key}`));
  integer(summary.total, `${path}.total`);
  integer(summary.covered, `${path}.covered`);
  requireValue(summary.total === STATUS_KEYS.reduce((total, key) => total + summary.statuses[key], 0), `${path}.total does not reconcile.`);
  requireValue(summary.covered === summary.statuses.declaration + summary.statuses.module, `${path}.covered does not reconcile.`);
  if (summary.total === 0) requireValue(summary.percentage === null, `${path}.percentage must be unavailable for an empty catalog.`);
  else close(summary.percentage, 100 * summary.covered / summary.total, `${path}.percentage`);
}

function validateFlow(flow, path) {
  if (flow === null) return;
  object(flow, path);
  const counts = ["gains", "losses", "added", "removed", "covered_added", "covered_removed", "documentation_gains", "source_gains", "unknown_gains"];
  counts.forEach((key) => integer(flow[key], `${path}.${key}`));
  integer(flow.net_covered, `${path}.net_covered`, -Number.MAX_SAFE_INTEGER);
  integer(flow.net_total, `${path}.net_total`, -Number.MAX_SAFE_INTEGER);
  requireValue(flow.covered_added <= flow.added && flow.covered_removed <= flow.removed, `${path} has impossible covered catalog edits.`);
  requireValue(flow.net_total === flow.added - flow.removed, `${path}.net_total does not reconcile.`);
  requireValue(flow.net_covered === flow.gains - flow.losses + flow.covered_added - flow.covered_removed, `${path}.net_covered does not reconcile.`);
  requireValue(flow.gains === flow.documentation_gains + flow.source_gains + flow.unknown_gains, `${path} gain contexts do not reconcile.`);
}

function validateComparison(comparison, months, path) {
  object(comparison, path);
  integer(comparison.cohort_size, `${path}.cohort_size`, 1);
  integer(comparison.excluded, `${path}.excluded`);
  for (const key of ["recent", "prior"]) {
    const rate = comparison[key];
    object(rate, `${path}.${key}`);
    integer(rate.gains, `${path}.${key}.gains`);
    integer(rate.losses, `${path}.${key}.losses`);
    integer(rate.net, `${path}.${key}.net`, -Number.MAX_SAFE_INTEGER);
    requireValue(rate.net === rate.gains - rate.losses, `${path}.${key}.net does not reconcile.`);
    close(rate.per_month, rate.net / months, `${path}.${key}.per_month`);
    close(rate.percentage_points, 100 * rate.net / comparison.cohort_size, `${path}.${key}.percentage_points`);
  }
  close(comparison.pace_change, comparison.recent.per_month - comparison.prior.per_month, `${path}.pace_change`);
}

function validateWindow(window, months, subjectIds, snapshot, path) {
  object(window, path);
  requireValue(typeof window.available === "boolean" && window.months === months, `${path} has an invalid window selection.`);
  date(window.end, `${path}.end`);
  requireValue(window.end <= snapshot.date, `${path} ends after its observation.`);
  for (const key of ["start", "prior_start"]) {
    if (window[key] !== null) date(window[key], `${path}.${key}`);
  }
  object(window.subjects, `${path}.subjects`);
  for (const [id, comparison] of Object.entries(window.subjects)) {
    requireValue(subjectIds.has(id), `${path} refers to an unknown subject.`);
    validateComparison(comparison, months, `${path}.subjects.${id}`);
  }
  validateFlow(window.flow, `${path}.flow`);
  if (window.available) {
    requireValue(window.reason === null && window.prior_start !== null && window.start !== null
      && window.prior_start < window.start && window.start < window.end, `${path} lacks valid comparison boundaries.`);
    validateComparison(window.overall, months, `${path}.overall`);
  } else {
    text(window.reason, `${path}.reason`);
    requireValue(window.overall === null && Object.keys(window.subjects).length === 0, `${path} must not display unavailable comparisons as data.`);
  }
}

function summaryOf(records) {
  const statuses = Object.fromEntries(STATUS_KEYS.map((status) => [status, 0]));
  for (const record of records) statuses[record.status] += 1;
  return statuses;
}

function applyEvent(benchmark, states, event, path) {
  const changed = new Set();
  array(event.changes, `${path}.changes`);
  for (const change of event.changes) {
    requireValue(Array.isArray(change) && change.length === 2, `${path} has a malformed change.`);
    const [id, index] = change;
    text(id, `${path} topic ID`);
    requireValue(!changed.has(id), `${path} repeats topic ID ${id}.`);
    changed.add(id);
    if (index === null) {
      requireValue(states.has(id), `${path} removes an absent topic.`);
      states.delete(id);
    } else {
      integer(index, `${path} record index`);
      requireValue(index < benchmark.records.length, `${path} points to a missing record.`);
      const record = benchmark.records[index];
      requireValue(record.id === id && record.source === event.source, `${path} has a record identity/source mismatch.`);
      states.set(id, record);
    }
  }
}

function validateBenchmark(benchmark, sourceIds, observedAt) {
  object(benchmark, "Benchmark");
  const path = benchmark.id;
  for (const key of ["title", "description", "scope"]) text(benchmark[key], `${path}.${key}`);
  array(benchmark.subjects, `${path}.subjects`, true);
  const subjectIds = new Set();
  for (const subject of benchmark.subjects) {
    object(subject, `${path} subject`);
    text(subject.id, `${path} subject ID`);
    text(subject.label, `${path} subject label`);
    requireValue(!subjectIds.has(subject.id), `${path} has a duplicate subject ID.`);
    subjectIds.add(subject.id);
  }
  array(benchmark.records, `${path}.records`, true);
  for (const record of benchmark.records) {
    object(record, `${path} record`);
    for (const key of ["id", "label", "subject"]) text(record[key], `${path} record ${key}`);
    requireValue(subjectIds.has(record.subject), `${path} record has an unknown subject.`);
    requireValue(has(STATUS_INFO, record.status), `${path} record has an unknown evidence status.`);
    requireValue(has(REPOSITORIES, record.source) && sourceIds.has(record.source), `${path} record has an unknown source.`);
    array(record.path, `${path} record path`);
    record.path.forEach((part) => text(part, `${path} record path part`));
    array(record.references, `${path} record references`);
    record.references.forEach((reference) => text(reference, `${path} reference`));
    requireValue(!covered(record) || record.references.length > 0, `${path} covered record lacks a reference.`);
    text(record.note, `${path} record note`, true);
    for (const key of ["authors", "reported_date"]) {
      if (record[key] !== null) text(record[key], `${path} record ${key}`, true);
    }
  }
  array(benchmark.events, `${path}.events`, true);
  const states = new Map();
  const inventories = [];
  let previousTime = -Infinity;
  for (const [index, event] of benchmark.events.entries()) {
    object(event, `${path} event`);
    timestamp(event.at, `${path} event observation`);
    timestamp(event.committed_at, `${path} event commit date`);
    requireValue(Date.parse(event.at) >= previousTime && Date.parse(event.at) <= Date.parse(observedAt), `${path} events are outside observation order.`);
    previousTime = Date.parse(event.at);
    requireValue(SHA.test(event.commit) && has(REPOSITORIES, event.source) && sourceIds.has(event.source), `${path} event lacks a valid source revision.`);
    requireValue(safeHttpUrl(event.url) !== null, `${path} event URL is not safe HTTP(S).`);
    text(event.summary, `${path} event summary`, true);
    requireValue(["documentation_only", "source_accompanied", "unknown"].includes(event.context), `${path} has unknown commit context.`);
    requireValue(event.initial === (index === 0), `${path} has an invalid initial catalog event.`);
    applyEvent(benchmark, states, event, `${path} event ${index}`);
    requireValue(states.size > 0, `${path} has an empty catalog observation.`);
    const groups = new Map();
    for (const record of states.values()) {
      if (!groups.has(record.subject)) groups.set(record.subject, []);
      groups.get(record.subject).push(record);
    }
    inventories.push({
      statuses: summaryOf(states.values()),
      subjects: new Map([...groups].map(([id, records]) => [id, summaryOf(records)])),
    });
  }
  array(benchmark.timeline, `${path}.timeline`);
  object(benchmark.latest, `${path}.latest`);
  let previousSnapshot = null;
  for (const snapshot of snapshotsFor(benchmark)) {
    const latest = snapshot === benchmark.latest;
    object(snapshot, `${path} snapshot`);
    date(snapshot.date, `${path} snapshot date`);
    timestamp(snapshot.as_of, `${path} snapshot observation`);
    timestamp(snapshot.commit_date, `${path} snapshot commit date`);
    requireValue(snapshot.kind === (latest ? "latest" : "monthly"), `${path} snapshot has an invalid kind.`);
    requireValue(new Date(snapshot.as_of).toISOString().slice(0, 10) === snapshot.date, `${path} snapshot date differs from its UTC cutoff.`);
    requireValue(Date.parse(snapshot.as_of) <= Date.parse(observedAt), `${path} snapshot is after the dataset observation.`);
    if (latest) requireValue(Date.parse(snapshot.as_of) === Date.parse(observedAt), `${path} latest observation is inconsistent with metadata.`);
    if (previousSnapshot) {
      requireValue(Date.parse(snapshot.as_of) >= Date.parse(previousSnapshot.as_of)
        && (latest || snapshot.date > previousSnapshot.date), `${path} snapshots are not chronological.`);
    }
    integer(snapshot.event_index, `${path} snapshot event index`);
    requireValue(snapshot.event_index < benchmark.events.length, `${path} snapshot points to a missing event.`);
    const event = benchmark.events[snapshot.event_index];
    const cutoff = Date.parse(snapshot.as_of);
    const nextEvent = benchmark.events[snapshot.event_index + 1];
    requireValue((latest ? Date.parse(event.at) <= cutoff : Date.parse(event.at) < cutoff)
      && (!nextEvent || (latest ? Date.parse(nextEvent.at) > cutoff : Date.parse(nextEvent.at) >= cutoff)),
    `${path} snapshot does not select the evidence at its cutoff.`);
    requireValue(snapshot.commit === event.commit && snapshot.source === event.source
      && Date.parse(snapshot.commit_date) === Date.parse(event.committed_at), `${path} snapshot source does not match its evidence.`);
    validateSummary(snapshot.overall, `${path} overall`);
    requireValue(snapshot.overall.total > 0, `${path} has an empty snapshot.`);
    const inventory = inventories[snapshot.event_index];
    requireValue(STATUS_KEYS.every((status) => inventory.statuses[status] === snapshot.overall.statuses[status]), `${path} snapshot counts differ from replayed evidence.`);
    sameKeys(snapshot.subjects, [...inventory.subjects.keys()], `${path} snapshot subjects`);
    for (const [id, summary] of Object.entries(snapshot.subjects)) {
      validateSummary(summary, `${path} subject ${id}`);
      requireValue(STATUS_KEYS.every((status) => summary.statuses[status] === inventory.subjects.get(id)[status]), `${path} subject counts differ from replayed evidence.`);
    }
    validateFlow(snapshot.flow, `${path} snapshot flow`);
    if (previousSnapshot) {
      requireValue(snapshot.flow !== null
        && snapshot.flow.net_covered === snapshot.overall.covered - previousSnapshot.overall.covered
        && snapshot.flow.net_total === snapshot.overall.total - previousSnapshot.overall.total, `${path} snapshot flow differs from its level change.`);
    }
    sameKeys(snapshot.windows, WINDOW_MONTHS.map(String), `${path} windows`);
    for (const months of WINDOW_MONTHS) validateWindow(snapshot.windows[String(months)], months, subjectIds, snapshot, `${path} ${months}-month window`);
    previousSnapshot = snapshot;
  }
  object(benchmark.diagnostics, `${path}.diagnostics`);
  array(benchmark.diagnostics.warnings, `${path}.diagnostics.warnings`);
  benchmark.diagnostics.warnings.forEach((warning) => text(warning, `${path} warning`));
  if (has(benchmark.diagnostics, "taxonomy")) object(benchmark.diagnostics.taxonomy, `${path} taxonomy`);
}

export function validatePayload(payload) {
  object(payload, "Coverage data");
  requireValue(payload.schema_version === SCHEMA_VERSION, `Unsupported coverage schema. This dashboard requires schema ${SCHEMA_VERSION}; refresh the code and data together.`);
  object(payload.meta, "meta");
  timestamp(payload.meta.observed_at, "meta.observed_at");
  timestamp(payload.meta.generated_at, "meta.generated_at");
  requireValue(Date.parse(payload.meta.generated_at) >= Date.parse(payload.meta.observed_at), "Generation predates the observation.");
  array(payload.meta.sources, "meta.sources", true);
  const sourceIds = new Set();
  for (const source of payload.meta.sources) {
    object(source, "Source");
    for (const key of ["name", "ref"]) text(source[key], `Source ${key}`);
    requireValue(!sourceIds.has(source.name), "Duplicate source ID.");
    sourceIds.add(source.name);
    requireValue(SHA.test(source.head), "A source is missing its full revision.");
    requireValue(safeHttpUrl(source.url) !== null, "A source URL is not safe HTTP(S).");
    timestamp(source.head_date, "Source head date");
  }
  array(payload.benchmarks, "benchmarks", true);
  requireValue(payload.benchmarks.length === BENCHMARK_IDS.length
    && BENCHMARK_IDS.every((id) => payload.benchmarks.filter((benchmark) => isObject(benchmark) && benchmark.id === id).length === 1),
  "Both distinct benchmarks, named and undergraduate, are required exactly once.");
  payload.benchmarks.forEach((benchmark) => validateBenchmark(benchmark, sourceIds, payload.meta.observed_at));
  return payload;
}

export function benchmarkFor(payload, id) {
  const benchmark = payload.benchmarks.find((item) => item.id === id);
  requireValue(benchmark !== undefined, `Unknown benchmark: ${id}.`);
  return benchmark;
}

export function snapshotsFor(benchmark) {
  return [...benchmark.timeline, benchmark.latest];
}

export function historyPoints(benchmark, subject = null) {
  if (subject !== null) {
    requireValue(benchmark.subjects.some((item) => item.id === subject), `Unknown subject: ${subject}.`);
  }
  let previous = null;
  return snapshotsFor(benchmark).map((snapshot, index) => {
    const summary = subject === null
      ? snapshot.overall
      : has(snapshot.subjects, subject) ? snapshot.subjects[subject] : null;
    const point = {
      index,
      snapshot,
      as_of: snapshot.as_of,
      kind: snapshot.kind,
      source: snapshot.source,
      available: summary !== null,
      covered: summary?.covered ?? null,
      total: summary?.total ?? null,
      percentage: summary?.percentage ?? null,
      delta_covered: summary !== null && previous !== null ? summary.covered - previous.covered : null,
    };
    previous = summary;
    return point;
  });
}

export function fittedPercentageDomain(points) {
  const values = points.map((point) => typeof point === "number" ? point : point?.percentage)
    .filter((value) => Number.isFinite(value));
  if (!values.length) return [0, 100];
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const span = maximum - minimum;
  const padding = Math.max(2.5, span * 0.12);
  let lower = Math.max(0, Math.floor((minimum - padding) / 5) * 5);
  let upper = Math.min(100, Math.ceil((maximum + padding) / 5) * 5);
  if (upper - lower < 10) {
    if (lower === 0) upper = Math.min(100, lower + 10);
    else if (upper === 100) lower = Math.max(0, upper - 10);
    else {
      lower = Math.max(0, lower - 5);
      upper = Math.min(100, upper + 5);
    }
  }
  return [lower, upper];
}

export function snapshotIndexForObservation(benchmark, observation) {
  const target = Date.parse(observation);
  requireValue(Number.isFinite(target), "Observation must be a valid timestamp.");
  const index = snapshotsFor(benchmark).findIndex((snapshot) => Date.parse(snapshot.as_of) === target);
  requireValue(index >= 0, `Unknown observation: ${observation}.`);
  return index;
}

export function windowFor(snapshot, months = 6) {
  requireValue(WINDOW_MONTHS.includes(Number(months)), "Choose a 3-, 6-, or 12-month window.");
  const window = snapshot.windows[String(months)];
  requireValue(isObject(window), "The selected comparison window is missing.");
  return window;
}

export function replayRecords(benchmark, eventIndex) {
  integer(eventIndex, "Event index", -1);
  requireValue(eventIndex < benchmark.events.length, "Event index is outside the available history.");
  const states = new Map();
  for (let index = 0; index <= eventIndex; index += 1) applyEvent(benchmark, states, benchmark.events[index], `Event ${index}`);
  return [...states.values()];
}

const normalize = (value) => String(value).normalize("NFKC").toLocaleLowerCase("en").trim();
const byLabel = (left, right) => left.label.localeCompare(right.label, "en") || left.id.localeCompare(right.id, "en");

function compareNullable(left, right, direction) {
  if (left === null) return right === null ? 0 : 1;
  if (right === null) return -1;
  return direction * (left - right);
}

export function subjectRows(benchmark, snapshot, window, { query = "", sort = "gaps" } = {}) {
  const needle = normalize(query);
  const rows = benchmark.subjects.filter((subject) => normalize(`${subject.label} ${subject.id}`).includes(needle)).map((subject) => {
    const summary = has(snapshot.subjects, subject.id) ? snapshot.subjects[subject.id] : null;
    const comparison = window.available && has(window.subjects, subject.id) ? window.subjects[subject.id] : null;
    return {
      ...subject, summary, comparison,
      remaining: summary ? summary.total - summary.covered : null,
      percentage: summary?.percentage ?? null,
      change: comparison?.recent.percentage_points ?? null,
    };
  });
  const orders = { gaps: ["remaining", -1], coverage: ["percentage", 1], change: ["change", -1] };
  return rows.sort((left, right) => {
    const order = orders[sort];
    return (order ? compareNullable(left[order[0]], right[order[0]], order[1]) : 0) || byLabel(left, right);
  });
}

export function filterRecords(records, { subject = null, status = "all", query = "" } = {}) {
  const needle = normalize(query);
  return records.filter((record) => (subject === null || record.subject === subject)
    && (status === "all" || (status === "covered" ? covered(record) : status === "not-covered" ? !covered(record) : record.status === status))
    && normalize([record.id, record.label, ...record.path, ...record.references, record.note, record.authors ?? ""].join(" ")).includes(needle))
    .sort(byLabel);
}

export function changesAt(benchmark, eventIndex) {
  requireValue(Number.isInteger(eventIndex) && eventIndex >= 0 && eventIndex < benchmark.events.length, "Change event is outside the available history.");
  const beforeRecords = new Map(replayRecords(benchmark, eventIndex - 1).map((record) => [record.id, record]));
  const event = benchmark.events[eventIndex];
  return event.changes.map(([id, index]) => {
    const before = beforeRecords.get(id) ?? null;
    const after = index === null ? null : benchmark.records[index];
    const kind = event.initial ? "baseline" : !before ? "addition" : !after ? "removal"
      : !covered(before) && covered(after) ? "gain" : covered(before) && !covered(after) ? "loss" : "edit";
    return { id, before, after, kind };
  });
}

export function eventsForSubject(benchmark, eventIndex, subject = null) {
  integer(eventIndex, "Event index", -1);
  requireValue(eventIndex < benchmark.events.length, "Event index is outside the available history.");
  const states = new Map();
  const events = [];
  for (let index = 0; index <= eventIndex; index += 1) {
    const event = benchmark.events[index];
    if (subject === null || event.changes.some(([id, recordIndex]) => states.get(id)?.subject === subject
      || (recordIndex !== null && benchmark.records[recordIndex].subject === subject))) events.push({ index, event });
    applyEvent(benchmark, states, event, `Event ${index}`);
  }
  return events;
}

export function formatCount(value) {
  return value === null || value === undefined ? "Unavailable" : new Intl.NumberFormat("en").format(value);
}

export function formatPercent(value) {
  return value === null || value === undefined ? "Unavailable" : `${value.toFixed(1)}%`;
}

export function formatSigned(value, digits = 0) {
  if (value === null || value === undefined) return "Unavailable";
  return new Intl.NumberFormat("en", { signDisplay: "exceptZero", minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
}

export function formatDate(value) {
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(new Date(value));
}

export function formatClosedMonths(start, end, { compact = false } = {}) {
  if (start === null || start === undefined || end === null || end === undefined) return "Unavailable";
  date(start, "Window start");
  date(end, "Window end");
  requireValue(start < end, "A closed-month interval must end after it starts.");
  const finalDay = new Date(`${end}T00:00:00Z`);
  finalDay.setUTCDate(finalDay.getUTCDate() - 1);
  const firstDay = new Date(`${start}T00:00:00Z`);
  const formatter = new Intl.DateTimeFormat("en-GB", { month: "short", year: "numeric", timeZone: "UTC" });
  if (compact && firstDay.getUTCFullYear() === finalDay.getUTCFullYear()) {
    if (firstDay.getUTCMonth() === finalDay.getUTCMonth()) return formatter.format(finalDay);
    const month = new Intl.DateTimeFormat("en-GB", { month: "short", timeZone: "UTC" });
    return `${month.format(firstDay)}–${formatter.format(finalDay)}`;
  }
  return `${formatter.format(firstDay)} – ${formatter.format(finalDay)}`;
}

export function formatTimestamp(value) {
  return `${new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }).format(new Date(value))} UTC`;
}

export function observationAge(observedAt, now = Date.now()) {
  const elapsed = now - Date.parse(observedAt);
  if (elapsed < -86_400_000) return { stale: true, label: "Observation date is in the future" };
  const days = Math.max(0, Math.floor(elapsed / 86_400_000));
  return { stale: days >= 7, label: days === 0 ? "Observed less than a day ago" : `Observation is ${days} day${days === 1 ? "" : "s"} old` };
}
