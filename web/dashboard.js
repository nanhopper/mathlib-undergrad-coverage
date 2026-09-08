import {
  DataValidationError, STATUS_INFO, STATUS_KEYS, benchmarkFor, changesAt, eventsForSubject,
  filterRecords, formatClosedMonths, formatCount, formatDate, formatPercent, formatSigned, formatTimestamp,
  observationAge, replayRecords, safeHttpUrl, snapshotsFor, sourceFileUrl, subjectRows,
  validatePayload, windowFor,
} from "./dashboard-model.js";

const PAGE_SIZE = 12;
const $ = (id) => document.getElementById(id);
const state = {
  data: null, benchmarkId: "named", snapshotIndex: 0, months: 6, records: [],
  subjectQuery: "", subjectSort: "gaps", allSubjects: false,
  evidenceSubject: "", evidenceStatus: "all", evidenceQuery: "", evidenceLimit: PAGE_SIZE,
  eventIndex: null, eventLimit: PAGE_SIZE, chartsAvailable: false,
};
const CONTEXT_LABELS = {
  documentation_only: "Documentation-only commit",
  source_accompanied: "Lean source changes in the same commit",
  unknown: "Commit context unknown",
};
const CHANGE_LABELS = {
  baseline: "Initial inventory", addition: "Catalog addition", removal: "Catalog removal",
  gain: "Recorded reference gain", loss: "Recorded reference loss", edit: "Evidence / label edit",
};

function node(tag, text = null, className = "") {
  const element = document.createElement(tag);
  if (text !== null) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function setText(id, text) {
  $(id).textContent = text;
}

function link(text, url) {
  const href = safeHttpUrl(url);
  const element = node(href ? "a" : "span", text);
  if (href) element.href = href;
  return element;
}

function option(value, label) {
  const element = node("option", label);
  element.value = String(value);
  return element;
}

function addPair(list, label, value) {
  const group = node("div");
  group.append(node("dt", label), node("dd", value));
  list.append(group);
}

function revealSection(id, focus = true) {
  const target = $(id);
  let disclosure = target.closest("details");
  while (disclosure) {
    disclosure.open = true;
    disclosure = disclosure.parentElement.closest("details");
  }
  if (focus) (target.tagName === "DETAILS" ? target.querySelector("summary") : target).focus();
}

function followSectionHash() {
  const target = $(location.hash.slice(1));
  if (target && !$("dashboard").hidden && $("dashboard").contains(target)) {
    revealSection(target.id, false);
    target.scrollIntoView({ block: "start" });
  }
}

function updateExplorerPlacement() {
  const explorer = $("explorer");
  const height = explorer.offsetHeight;
  const sticky = window.innerWidth >= 1000 && height > 0 && height < window.innerHeight / 4;
  explorer.classList.toggle("is-sticky", sticky);
  const gap = 2 * parseFloat(getComputedStyle(explorer).fontSize);
  document.documentElement.style.setProperty("--explorer-offset", sticky ? `${height + gap}px` : "1rem");
}

function selected() {
  const benchmark = benchmarkFor(state.data, state.benchmarkId);
  const snapshots = snapshotsFor(benchmark);
  const snapshot = snapshots[state.snapshotIndex];
  return { benchmark, snapshots, snapshot, window: windowFor(snapshot, state.months) };
}

function countLabel(summary) {
  return `${formatCount(summary.covered)} / ${formatCount(summary.total)}`;
}

function bar(element, value) {
  element.style.width = `${value ?? 0}%`;
}

function revisionUrl(source) {
  const url = safeHttpUrl(source.url);
  return url ? `${url.replace(/\/$/, "").replace(/\.git$/, "")}/tree/${source.head}` : null;
}

function renderOverview() {
  for (const benchmark of state.data.benchmarks) {
    const { id, latest } = benchmark;
    setText(`${id}-title`, benchmark.title);
    setText(`${id}-percentage`, formatPercent(latest.overall.percentage));
    setText(`${id}-count`, `${formatCount(latest.overall.covered)} of ${formatCount(latest.overall.total)} listed entries`);
    bar($(`${id}-bar`), latest.overall.percentage);
    const pace = windowFor(latest, 6);
    const headline = $(`${id}-pace`);
    headline.replaceChildren(document.createTextNode("6-mo pace: "));
    if (pace.available) {
      headline.append(
        node("strong", `${formatSigned(pace.overall.recent.per_month, 2)} net entries/mo`),
        document.createTextNode(` (was ${formatSigned(pace.overall.prior.per_month, 2)}) · ${formatClosedMonths(pace.start, pace.end, { compact: true })}`));
    } else {
      headline.append(node("strong", "Unavailable"), node("span", pace.reason, "pace-reason"));
    }
  }
  const { meta } = state.data;
  setText("observed-at", formatTimestamp(meta.observed_at));
  const age = observationAge(meta.observed_at);
  setText("observation-age", `${age.label}.`);
  $("observation-age").classList.toggle("is-stale", age.stale);
  const activeSource = meta.sources.find((source) => source.name === "mathlib4");
  $("source-status").replaceChildren();
  if (activeSource) {
    $("source-status").append(link(`${activeSource.name} @ ${activeSource.head.slice(0, 8)}`, revisionUrl(activeSource)));
    $("source-status").title = `Source head committed ${formatTimestamp(activeSource.head_date)}. Full revisions and timestamps are under Methods & sources.`;
  }
  for (const item of $("benchmark-select").options) item.textContent = benchmarkFor(state.data, item.value).title;
}

function renderObservationOptions() {
  const { benchmark, snapshots } = selected();
  $("benchmark-select").value = benchmark.id;
  $("observation-select").replaceChildren(...snapshots.map((snapshot, index) => option(index,
    `${snapshot.kind === "latest" ? "Latest" : "Monthly cutoff"} · ${formatDate(snapshot.as_of)}`)).reverse());
  $("observation-select").value = String(state.snapshotIndex);
}

function renderSelection() {
  const { benchmark, snapshot } = selected();
  const historical = snapshot.kind !== "latest";
  setText("selection-badge", historical ? "Historical observation" : "Latest observation");
  $("selection-badge").classList.toggle("historical", historical);
  $("historical-notice").hidden = !historical;
  setText("selection-detail", `${formatTimestamp(snapshot.as_of)} · ${snapshot.source}`);
  setText("analysis-context", `${benchmark.title} · ${formatTimestamp(snapshot.as_of)}`);
  $("selection-source").href = sourceFileUrl(benchmark.id, snapshot);
  $("selection-source").title = `Catalog commit ${formatTimestamp(snapshot.commit_date)}. Open the source YAML at this exact revision.`;
  setText("selection-source", `Selected catalog YAML @ ${snapshot.commit.slice(0, 8)}`);
  setText("selected-level", `${countLabel(snapshot.overall)} recorded · ${formatPercent(snapshot.overall.percentage)}`);
  $("observation-select").value = String(state.snapshotIndex);
}

function documentationBatches(benchmark, snapshot, firstDate) {
  return benchmark.events.map((event, index) => ({ event, index }))
    .filter(({ event, index }) => index <= snapshot.event_index && !event.initial && event.context === "documentation_only"
      && event.changes.length >= 5 && Date.parse(event.at) >= firstDate)
    .sort((left, right) => right.event.changes.length - left.event.changes.length || right.index - left.index)
    .slice(0, 3).sort((left, right) => left.index - right.index);
}

function chartLibraryAvailable() {
  return ["select", "scaleUtc", "scaleLinear", "axisLeft", "axisBottom", "line", "utcFormat", "extent"]
    .every((name) => typeof globalThis.d3?.[name] === "function") && typeof globalThis.d3?.curveStepAfter === "function";
}

function setChartAvailability(available) {
  $("chart-warning").hidden = available;
  $("history-chart").toggleAttribute("hidden", !available);
  $("chart-unavailable").hidden = available;
}

function drawHistory() {
  if (!state.data) return;
  setChartAvailability(state.chartsAvailable);
  if (!state.chartsAvailable || !$("analysis-section").open) return;
  try {
    const d3 = globalThis.d3;
    const { benchmark, snapshots, snapshot } = selected();
    const series = snapshots.slice(0, state.snapshotIndex + 1);
    const points = series.map((entry) => ({ date: new Date(entry.as_of), value: entry.overall.percentage }));
    const width = Math.max(280, $("history-chart").parentElement.clientWidth || 900);
    const height = width < 500 ? 260 : 300;
    const margin = { top: 32, right: 18, bottom: 38, left: 45 };
    const svg = d3.select($("history-chart"));
    svg.selectAll("*").remove();
    svg.attr("viewBox", `0 0 ${width} ${height}`);
    svg.append("title").attr("id", "history-chart-title").text(`${benchmark.title}: recorded coverage history`);
    svg.append("desc").attr("id", "history-chart-description").text(
      `${series.length} observations through ${formatDate(snapshot.as_of)}. Selected: ${countLabel(snapshot.overall)} entries, ${formatPercent(snapshot.overall.percentage)}. `
      + "A stepped line joins observed percentages on a zero to 100 percent scale; it does not interpolate proof dates. The full data table follows.");
    let domain = d3.extent(points, (point) => point.date);
    if (+domain[0] === +domain[1]) domain = [new Date(+domain[0] - 86_400_000), new Date(+domain[1] + 86_400_000)];
    const x = d3.scaleUtc().domain(domain).range([margin.left, width - margin.right]);
    const y = d3.scaleLinear().domain([0, 100]).range([height - margin.bottom, margin.top]);
    svg.append("g").attr("class", "chart-grid").attr("transform", `translate(${margin.left},0)`)
      .call(d3.axisLeft(y).tickValues([0, 25, 50, 75, 100]).tickSize(-(width - margin.left - margin.right)).tickFormat(""));
    svg.append("g").attr("class", "chart-axis").attr("transform", `translate(0,${height - margin.bottom})`)
      .call(d3.axisBottom(x).ticks(width < 500 ? 3 : 6).tickSizeOuter(0).tickFormat(d3.utcFormat(series.length === 1 ? "%d %b" : "%b %Y")));
    svg.append("g").attr("class", "chart-axis").attr("transform", `translate(${margin.left},0)`)
      .call(d3.axisLeft(y).tickValues([0, 25, 50, 75, 100]).tickSizeOuter(0).tickFormat((value) => `${value}%`));
    benchmark.events.slice(0, snapshot.event_index + 1).forEach((event, index) => {
      if (index === 0 || event.source === benchmark.events[index - 1].source || Date.parse(event.at) < +points[0].date) return;
      const position = x(new Date(event.at));
      svg.append("line").attr("class", "source-boundary").attr("x1", position).attr("x2", position)
        .attr("y1", margin.top).attr("y2", height - margin.bottom);
      svg.append("text").attr("class", "source-boundary-label").attr("x", position + 4).attr("y", 12).text(event.source);
    });
    svg.append("path").datum(points).attr("class", "coverage-line")
      .attr("d", d3.line().curve(d3.curveStepAfter).x((point) => x(point.date)).y((point) => y(point.value)));
    svg.selectAll(".coverage-point").data(points).join("circle").attr("class", "coverage-point")
      .attr("cx", (point) => x(point.date)).attr("cy", (point) => y(point.value)).attr("r", points.length > 60 ? 1.5 : 2);
    const chosen = points.at(-1);
    svg.append("circle").attr("class", "selected-point").attr("cx", x(chosen.date)).attr("cy", y(chosen.value)).attr("r", 5);
    documentationBatches(benchmark, snapshot, +points[0].date).forEach(({ event }) => {
      svg.append("rect").attr("class", "doc-marker").attr("x", x(new Date(event.at)) - 3.5).attr("y", 19).attr("width", 7).attr("height", 7)
        .append("title").text(`Documentation-only catalog batch: ${formatDate(event.at)}, ${event.changes.length} record edits. Not a proof date.`);
    });
  } catch (error) {
    console.warn("The coverage chart is unavailable; textual data is still shown.", error);
    state.chartsAvailable = false;
    setChartAvailability(false);
  }
}

function renderHistory() {
  const { benchmark, snapshots, snapshot } = selected();
  const series = snapshots.slice(0, state.snapshotIndex + 1);
  setText("history-caption", `${benchmark.title} · observations through ${formatTimestamp(snapshot.as_of)}. Percentages use each row’s own catalog denominator.`);
  $("history-rows").replaceChildren(...[...series].reverse().map((entry) => {
    const row = node("tr");
    const observation = node("th", formatDate(entry.as_of));
    observation.scope = "row";
    observation.append(node("span", entry.kind === "latest" ? "Latest / as of" : "Monthly cutoff", "table-subheading"));
    row.append(observation, node("td", entry.source), node("td", countLabel(entry.overall)),
      node("td", formatPercent(entry.overall.percentage)), node("td", entry.flow === null ? "Baseline" : formatSigned(entry.flow.net_covered)));
    return row;
  }));
  const initial = benchmark.events[0];
  const batches = documentationBatches(benchmark, snapshot, Date.parse(series[0].as_of));
  setText("history-range", `${series.length} observation${series.length === 1 ? "" : "s"} shown, through ${formatDate(snapshot.as_of)}. `
    + `The first catalog event (${formatDate(initial.at)}) is a baseline, not an assumed earlier zero.`
    + (batches.length ? " Batch markers show up to three of the largest documentation-only commits with at least five record edits." : ""));
  $("history-context").replaceChildren();
  for (const { event, index } of batches) {
    const button = node("button", `Inspect docs-only batch · ${formatDate(event.at)} · ${formatCount(event.changes.length)} record edits`, "text-button");
    button.type = "button";
    button.addEventListener("click", () => {
      state.evidenceSubject = "";
      state.eventIndex = index;
      state.eventLimit = PAGE_SIZE;
      $("evidence-subject").value = "";
      renderEvidence();
      renderEvents();
      revealSection("events-heading");
    });
    $("history-context").append(button);
  }
  drawHistory();
}

function flowDescription(flow) {
  return `${formatCount(flow.gains)} existing-entry reference gains − ${formatCount(flow.losses)} losses `
    + `+ ${formatCount(flow.covered_added)} referenced additions − ${formatCount(flow.covered_removed)} referenced removals `
    + `= ${formatSigned(flow.net_covered)} recorded entries. Catalog size: ${formatSigned(flow.net_total)}.`;
}

function renderPace() {
  const { benchmark, snapshot, window } = selected();
  const recentDates = window.start ? `${formatDate(window.start)} → ${formatDate(window.end)}` : `ending ${formatDate(window.end)}`;
  const priorDates = window.prior_start && window.start ? `${formatDate(window.prior_start)} → ${formatDate(window.start)}` : "Unavailable";
  const recentMonths = formatClosedMonths(window.start, window.end, { compact: true });
  setText("period-caption", window.start
    ? `${window.available ? "Recent" : "Requested"} window: ${recentMonths} · ${state.months} complete months.`
    : `Closed-window comparison unavailable · ${state.months} months · requested end cutoff ${formatDate(window.end)} UTC.`);
  $("period-caption").title = `UTC cutoffs: ${recentDates}; end excluded.`;
  $("pace-available").hidden = !window.available;
  $("pace-unavailable").hidden = window.available;
  if (!window.available) {
    $("pace-unavailable").replaceChildren(node("strong", "Comparable pace unavailable"), node("p", window.reason));
  } else {
    const comparison = window.overall;
    setText("recent-period", recentMonths);
    setText("prior-period", formatClosedMonths(window.prior_start, window.start, { compact: true }));
    $("recent-period").title = `${recentDates} UTC; end cutoff excluded`;
    $("prior-period").title = `${priorDates} UTC; end cutoff excluded`;
    for (const key of ["recent", "prior"]) {
      const rate = comparison[key];
      setText(`${key}-pace`, formatSigned(rate.per_month, 2));
      setText(`${key}-counts`, `${formatCount(rate.gains)} gains · ${formatCount(rate.losses)} losses · ${formatSigned(rate.percentage_points, 1)} percentage points`);
    }
    setText("pace-difference", `${formatSigned(comparison.pace_change, 2)} net recorded entries / month versus the previous window.`);
    setText("cohort-caption", `${formatCount(comparison.cohort_size)} continuously listed entries in both windows · `
      + `${formatCount(comparison.excluded)} historical identities excluded.`);
  }
  const flow = window.flow;
  $("flow-values").replaceChildren();
  $("flow-unavailable").hidden = flow !== null;
  setText("flow-reconciliation", "");
  setText("flow-context", "");
  if (flow === null) {
    setText("flow-unavailable", "Full-catalog flow for this closed window is unavailable.");
  } else {
    addPair($("flow-values"), "Existing entries gaining a reference", formatCount(flow.gains));
    addPair($("flow-values"), "Existing entries losing a reference", formatCount(flow.losses));
    addPair($("flow-values"), "Catalog additions / removals", `${formatCount(flow.added)} / ${formatCount(flow.removed)}`);
    addPair($("flow-values"), "Of those, referenced additions / removals", `${formatCount(flow.covered_added)} / ${formatCount(flow.covered_removed)}`);
    addPair($("flow-values"), "Net recorded entries", formatSigned(flow.net_covered));
    setText("flow-reconciliation", flowDescription(flow));
    setText("flow-context", `Context for the ${formatCount(flow.gains)} existing-entry gains: `
      + `${formatCount(flow.documentation_gains)} documentation-only, ${formatCount(flow.source_gains)} accompanied by Lean source changes, `
      + `${formatCount(flow.unknown_gains)} unknown. Context does not establish a formalization date.`);
  }
  const previous = benchmark.timeline.at(-1);
  const partial = snapshot.kind === "latest" && previous && snapshot.flow !== null
    && (Date.parse(snapshot.as_of) > Date.parse(previous.as_of) || snapshot.event_index > previous.event_index);
  $("partial-month").hidden = !partial;
  if (partial) {
    setText("partial-title", `Latest-only changes since the ${formatDate(previous.as_of)} monthly cutoff`);
    setText("partial-description", `${formatTimestamp(previous.as_of)} → ${formatTimestamp(snapshot.as_of)}. `
      + `This latest-only interval, including any events at the cutoff, is excluded from the closed-window comparison. ${flowDescription(snapshot.flow)}`);
  }
}

function subjectCell(label, className = "") {
  const cell = node("td", null, className);
  cell.setAttribute("role", "cell");
  const mobileLabel = node("span", label, "mobile-label");
  mobileLabel.setAttribute("aria-hidden", "true");
  cell.append(mobileLabel);
  return cell;
}

function inspectSubject(id, focus = false) {
  state.evidenceSubject = id;
  state.evidenceLimit = PAGE_SIZE;
  state.eventIndex = null;
  state.eventLimit = PAGE_SIZE;
  $("evidence-subject").value = id;
  renderEvidence();
  renderEvents();
  if (focus) revealSection("evidence-heading");
}

function renderSubjects() {
  const { benchmark, snapshot, window } = selected();
  const rows = subjectRows(benchmark, snapshot, window, { query: state.subjectQuery, sort: state.subjectSort });
  const visible = state.allSubjects ? rows : rows.slice(0, PAGE_SIZE);
  setText("subjects-caption", `${benchmark.title}: subject coverage at ${formatDate(snapshot.as_of)}. `
    + `${state.months}-month same-cohort changes end at ${formatDate(window.end)}. Select a subject to inspect its evidence.`);
  setText("subject-change-heading", `${state.months}-month change`);
  setText("subjects-period", window.available
    ? `Change: ${formatClosedMonths(window.start, window.end, { compact: true })}`
    : `Change unavailable · ${state.months}-month window`);
  setText("subject-window-explanation", window.available
    ? `Changes use each subject’s continuously listed cohort, not the selected catalog’s denominator. `
      + `The recent window runs from ${formatDate(window.start)} to ${formatDate(window.end)} UTC, with the end cutoff excluded. Missing cohorts are unavailable.`
    : window.reason);
  const sortedColumns = {
    gaps: ["subject-gap-column", "descending"], coverage: ["subject-coverage-column", "ascending"],
    change: ["subject-change-column", "descending"], name: ["subject-name-column", "ascending"],
  };
  for (const [id] of Object.values(sortedColumns)) $(id).removeAttribute("aria-sort");
  const [column, direction] = sortedColumns[state.subjectSort];
  $(column).setAttribute("aria-sort", direction);
  $("subject-rows").replaceChildren(...visible.map((subject) => {
    const row = node("tr");
    row.setAttribute("role", "row");
    const name = node("th");
    name.scope = "row";
    name.setAttribute("role", "rowheader");
    const button = node("button", subject.label, "subject-link");
    button.type = "button";
    button.setAttribute("aria-label", `Inspect evidence for ${subject.label}`);
    button.setAttribute("aria-controls", "evidence-section");
    const arrow = node("span", "→", "subject-arrow");
    arrow.setAttribute("aria-hidden", "true");
    button.append(arrow);
    button.addEventListener("click", () => inspectSubject(subject.id, true));
    name.append(button);
    const counts = subjectCell("Recorded / listed");
    counts.append(node("span", subject.summary ? countLabel(subject.summary) : "Not listed", subject.summary ? "cell-value" : "unavailable"));
    const percentage = subjectCell("Coverage", "coverage-cell");
    percentage.append(node("span", formatPercent(subject.percentage), subject.percentage === null ? "unavailable" : "cell-value"));
    if (subject.percentage !== null) {
      const track = node("div", null, "coverage-track");
      track.setAttribute("aria-hidden", "true");
      const fill = node("span");
      bar(fill, subject.percentage);
      track.append(fill);
      percentage.append(track);
    }
    const change = subjectCell(`${state.months}-month change`);
    if (subject.comparison) {
      change.append(node("span", `${formatSigned(subject.change, 1)} pp`, "comparison-value"),
        node("span", `${formatSigned(subject.comparison.recent.net)} entries · ${formatCount(subject.comparison.cohort_size)} in cohort`, "table-subheading"));
    } else {
      change.append(node("span", "Unavailable", "unavailable"));
      if (window.available || !subject.summary) {
        change.append(node("span", subject.summary ? "No common subject cohort" : "Not listed at this observation", "table-subheading"));
      }
    }
    const gap = subjectCell("No repo reference");
    gap.append(node("span", formatCount(subject.remaining), subject.remaining === null ? "unavailable" : "cell-value"));
    row.append(name, counts, percentage, change, gap);
    return row;
  }));
  if (rows.length === 0) {
    const row = node("tr");
    row.setAttribute("role", "row");
    const cell = node("td", "No subjects match. Try a broader subject name or MSC code.", "empty-state");
    cell.colSpan = 5;
    cell.setAttribute("role", "cell");
    row.append(cell);
    $("subject-rows").append(row);
  }
  const absent = rows.filter((row) => row.summary === null).length;
  setText("subject-count", `Showing ${visible.length} of ${rows.length} matching subjects.`
    + (absent ? ` ${absent} not listed at this observation.` : ""));
  $("subjects-more").hidden = rows.length <= PAGE_SIZE;
  $("subjects-more").setAttribute("aria-expanded", String(state.allSubjects));
  setText("subjects-more", state.allSubjects ? `Show the first ${PAGE_SIZE} subjects` : `Show all ${rows.length} subjects`);
}

function renderEvidenceOptions() {
  const { benchmark, snapshot } = selected();
  $("evidence-subject").replaceChildren(option("", "All subjects"),
    ...[...benchmark.subjects].sort((a, b) => a.label.localeCompare(b.label, "en")).map((subject) => option(subject.id,
      `${subject.label}${Object.hasOwn(snapshot.subjects, subject.id) ? "" : " · not listed at this observation"}`)));
  $("evidence-subject").value = state.evidenceSubject;
}

function recordBody(record, benchmark, observation) {
  const body = node("div", null, "evidence-body");
  if (record.path.length) body.append(node("p", record.path.join(" › "), "record-path"));
  const fields = node("dl", null, "record-fields");
  const subject = benchmark.subjects.find((item) => item.id === record.subject);
  fields.append(node("dt", "Entry ID"), node("dd", record.id), node("dt", "Subject"), node("dd", subject.label),
    node("dt", "Evidence"), node("dd", STATUS_INFO[record.status].label), node("dt", "Recorded source"), node("dd", record.source));
  if (record.authors) fields.append(node("dt", "Reported authors"), node("dd", record.authors));
  if (record.reported_date) fields.append(node("dt", "Reported date"), node("dd", `${record.reported_date} (as recorded)`));
  body.append(fields, node("p", STATUS_INFO[record.status].description, "small muted"));
  if (record.references.length) {
    body.append(node("strong", "Recorded references"));
    const references = node("ul", null, "reference-list");
    for (const reference of record.references) {
      const item = node("li");
      item.append(safeHttpUrl(reference) ? link(reference, reference) : node("code", reference));
      references.append(item);
    }
    body.append(references);
  } else {
    body.append(node("p", "No reference is recorded for this entry.", "small muted"));
  }
  if (record.note) body.append(node("p", record.note, "record-note"));
  const source = node("p", null, "small");
  source.append(link(`Source YAML at ${observation.commit.slice(0, 8)}`, sourceFileUrl(benchmark.id, observation)),
    document.createTextNode(" · reference names and relative paths are preserved, not guessed into current documentation links."));
  body.append(source);
  return body;
}

function renderEvidence() {
  const { benchmark, snapshot } = selected();
  const subject = benchmark.subjects.find((item) => item.id === state.evidenceSubject);
  const subjectLabel = subject?.label ?? "All subjects";
  setText("evidence-context", `${subjectLabel} · catalog evidence at ${formatTimestamp(snapshot.as_of)}`);
  const subjectRecords = filterRecords(state.records, { subject: state.evidenceSubject || null });
  const matches = filterRecords(subjectRecords, { status: state.evidenceStatus, query: state.evidenceQuery });
  const visible = matches.slice(0, state.evidenceLimit);
  $("status-inventory").replaceChildren();
  if (subject && !Object.hasOwn(snapshot.subjects, subject.id)) {
    addPair($("status-inventory"), "Subject not listed at this observation", "Evidence counts and coverage are unavailable, not zero.");
  } else {
    for (const status of STATUS_KEYS) {
      const count = subjectRecords.filter((record) => record.status === status).length;
      addPair($("status-inventory"), `${STATUS_INFO[status].label} · ${formatCount(count)}`, STATUS_INFO[status].description);
    }
  }
  const expanded = new Set([...$("evidence-list").querySelectorAll("details[open]")].map((item) => item.dataset.record));
  $("evidence-list").replaceChildren(...visible.map((record) => {
    const item = node("li");
    const disclosure = node("details");
    disclosure.dataset.record = record.id;
    disclosure.open = expanded.has(record.id);
    const summary = node("summary");
    const badge = node("span", STATUS_INFO[record.status].label, "status-badge");
    badge.dataset.status = record.status;
    summary.append(node("span", record.label, "evidence-name"), badge);
    disclosure.append(summary, recordBody(record, benchmark, snapshot));
    item.append(disclosure);
    return item;
  }));
  if (!matches.length) {
    $("evidence-list").append(node("li", subjectRecords.length === 0
      ? "This subject has no listed entries at this observation. That is not a zero-coverage claim."
      : "No entries match these filters. Try another evidence class or search term.", "empty-state"));
  }
  setText("evidence-count", `Showing ${formatCount(visible.length)} of ${formatCount(matches.length)} matching entries.`);
  $("evidence-more").hidden = visible.length >= matches.length;
  setText("evidence-more", `Show ${Math.min(PAGE_SIZE, matches.length - visible.length)} more entries`);
}

function changeSide(title, record, benchmark, observation) {
  const side = node("div", null, "change-side");
  side.append(node("h5", title));
  if (record) side.append(node("p", record.label, "small"), recordBody(record, benchmark, observation));
  else side.append(node("p", "Not in the catalog.", "small muted"));
  return side;
}

function renderEvents() {
  const { benchmark, snapshot } = selected();
  const subject = benchmark.subjects.find((item) => item.id === state.evidenceSubject);
  setText("event-subject-context", `Events through this observation for ${subject?.label ?? "all subjects"}. `
    + "The topic search and status filter above apply to the entry list, not to this commit history.");
  const events = eventsForSubject(benchmark, snapshot.event_index, state.evidenceSubject || null).reverse();
  if (!events.some(({ index }) => index === state.eventIndex)) state.eventIndex = events[0]?.index ?? null;
  $("event-select").replaceChildren(...events.map(({ event, index }) => option(index,
    `${formatDate(event.at)} · ${event.initial ? "Baseline" : event.source} · ${event.summary.length > 95 ? `${event.summary.slice(0, 92)}…` : event.summary}`)));
  $("event-empty").hidden = events.length > 0;
  $("event-detail").hidden = events.length === 0;
  $("event-select").disabled = events.length === 0;
  if (!events.length) {
    $("event-select").append(option("", "No catalog events for this subject"));
    return;
  }
  $("event-select").value = String(state.eventIndex);
  const event = benchmark.events[state.eventIndex];
  const changes = changesAt(benchmark, state.eventIndex).filter((change) => state.evidenceSubject === ""
    || change.before?.subject === state.evidenceSubject || change.after?.subject === state.evidenceSubject);
  const visible = changes.slice(0, state.eventLimit);
  setText("event-summary", event.summary || "Catalog revision");
  setText("event-context", CONTEXT_LABELS[event.context]);
  $("event-provenance").replaceChildren(document.createTextNode(`Recorded ${formatTimestamp(event.at)} · committed ${formatTimestamp(event.committed_at)} · `),
    link(`${event.source} @ ${event.commit.slice(0, 8)}`, event.url));
  $("event-baseline").hidden = !event.initial;
  if (event.initial) setText("event-counts", `${formatCount(changes.length)} entries in the initial inventory for this subject selection.`);
  else setText("event-counts", ["gain", "loss", "addition", "removal", "edit"].map((kind) =>
    `${formatCount(changes.filter((change) => change.kind === kind).length)} ${{
      gain: "reference gains", loss: "reference losses", addition: "catalog additions", removal: "catalog removals", edit: "evidence / label edits",
    }[kind]}`).join(" · "));
  const expanded = new Set([...$("event-changes").querySelectorAll("details[open]")].map((item) => item.dataset.change));
  $("event-changes").replaceChildren(...visible.map((change) => {
    const item = node("li");
    const disclosure = node("details");
    disclosure.dataset.change = `${state.eventIndex}:${change.id}`;
    disclosure.open = expanded.has(disclosure.dataset.change);
    const summary = node("summary");
    const badge = node("span", CHANGE_LABELS[change.kind], "change-badge");
    badge.dataset.kind = change.kind;
    summary.append(node("span", (change.after ?? change.before).label, "evidence-name"), badge);
    const detail = node("div", null, "change-detail");
    detail.append(changeSide("Before this event", change.before, benchmark, benchmark.events[state.eventIndex - 1]),
      changeSide("After this event", change.after, benchmark, event));
    disclosure.append(summary, detail);
    item.append(disclosure);
    return item;
  }));
  if (!changes.length) $("event-changes").append(node("li", "No topic-record changes in this catalog commit for the selected subject.", "empty-state"));
  setText("event-change-count", `Showing ${formatCount(visible.length)} of ${formatCount(changes.length)} changed entries.`);
  $("event-more").hidden = visible.length >= changes.length;
  setText("event-more", `Show ${Math.min(PAGE_SIZE, changes.length - visible.length)} more changes`);
}

function renderMethodology() {
  $("benchmark-methods").replaceChildren(...state.data.benchmarks.map((benchmark) => {
    const section = node("div");
    section.append(node("h3", benchmark.title), node("p", benchmark.description), node("p", benchmark.scope));
    const statuses = benchmark.latest.overall.statuses;
    const breakdown = STATUS_KEYS.filter((status) => statuses[status] > 0)
      .map((status) => `${STATUS_INFO[status].label}: ${formatCount(statuses[status])}`).join(" · ");
    section.append(node("p", `Latest evidence (${formatDate(benchmark.latest.as_of)}): ${breakdown}.`, "small"));
    return section;
  }));
  const { meta } = state.data;
  setText("generation-detail", `Observed ${formatTimestamp(meta.observed_at)}; generated ${formatTimestamp(meta.generated_at)}. `
    + "Observation age describes this artifact, not how recently a theorem was formalized. Archived repositories and pinned taxonomy sources need not be recently edited.");
  $("source-list").replaceChildren(...meta.sources.map((source) => {
    const item = node("li");
    item.append(node("strong", `${source.name} · ${source.ref}`),
      node("p", `Source head committed ${formatTimestamp(source.head_date)}.`, "small muted"),
      link(source.head, revisionUrl(source)));
    return item;
  }));
  $("diagnostics").replaceChildren(...state.data.benchmarks.map((benchmark) => {
    const section = node("div", null, "diagnostic-block");
    section.append(node("h3", `${benchmark.title}: data-quality notes`));
    const warnings = node("ul");
    for (const warning of benchmark.diagnostics.warnings) warnings.append(node("li", warning));
    section.append(warnings);
    const extra = Object.fromEntries(Object.entries(benchmark.diagnostics).filter(([key]) => key !== "warnings"));
    if (Object.keys(extra).length) {
      const detail = node("details");
      detail.append(node("summary", "Inspect pinned taxonomy and reconciliation metadata"));
      if (safeHttpUrl(extra.taxonomy?.url)) {
        const paragraph = node("p");
        paragraph.append(link("Pinned taxonomy source", extra.taxonomy.url));
        detail.append(paragraph);
      }
      const raw = node("pre", JSON.stringify(extra, null, 2));
      raw.tabIndex = 0;
      raw.setAttribute("aria-label", `${benchmark.title} diagnostic metadata`);
      detail.append(raw);
      section.append(detail);
    }
    return section;
  }));
}

function renderSelected() {
  const { benchmark, snapshot } = selected();
  state.records = replayRecords(benchmark, snapshot.event_index);
  renderSelection();
  renderHistory();
  renderPace();
  renderSubjects();
  renderEvidenceOptions();
  renderEvidence();
  renderEvents();
}

function chooseBenchmark(id, focus = false) {
  state.benchmarkId = id;
  state.snapshotIndex = benchmarkFor(state.data, id).timeline.length;
  state.subjectQuery = "";
  state.subjectSort = "gaps";
  state.allSubjects = false;
  state.evidenceSubject = "";
  state.evidenceStatus = "all";
  state.evidenceQuery = "";
  state.evidenceLimit = PAGE_SIZE;
  state.eventIndex = null;
  state.eventLimit = PAGE_SIZE;
  $("subject-search").value = "";
  $("subject-sort").value = "gaps";
  $("evidence-search").value = "";
  $("evidence-status").value = "all";
  renderObservationOptions();
  renderSelected();
  if (focus) $("benchmark-select").focus();
}

function bindControls() {
  $("retry").addEventListener("click", load);
  document.querySelectorAll('a[href^="#"]').forEach((anchor) => anchor.addEventListener("click", () => {
    revealSection(anchor.hash.slice(1), false);
  }));
  window.addEventListener("hashchange", followSectionHash);
  $("analysis-section").addEventListener("toggle", drawHistory);
  new ResizeObserver(updateExplorerPlacement).observe($("explorer"));
  $("chart-library").addEventListener("load", () => {
    state.chartsAvailable = chartLibraryAvailable();
    drawHistory();
  });
  $("benchmark-select").addEventListener("change", (event) => chooseBenchmark(event.target.value));
  for (const id of ["named", "undergraduate"]) $(`explore-${id}`).addEventListener("click", () => chooseBenchmark(id, true));
  $("observation-select").addEventListener("change", (event) => {
    state.snapshotIndex = Number(event.target.value);
    state.eventIndex = null;
    state.eventLimit = PAGE_SIZE;
    state.evidenceLimit = PAGE_SIZE;
    renderSelected();
  });
  document.querySelectorAll('input[name="window"]').forEach((input) => input.addEventListener("change", () => {
    if (!input.checked) return;
    state.months = Number(input.value);
    renderPace();
    renderSubjects();
  }));
  $("subject-search").addEventListener("input", (event) => {
    state.subjectQuery = event.target.value;
    state.allSubjects = false;
    renderSubjects();
  });
  $("subject-sort").addEventListener("change", (event) => {
    state.subjectSort = event.target.value;
    renderSubjects();
  });
  $("subjects-more").addEventListener("click", () => {
    state.allSubjects = !state.allSubjects;
    renderSubjects();
  });
  $("evidence-subject").addEventListener("change", (event) => inspectSubject(event.target.value));
  $("evidence-status").addEventListener("change", (event) => {
    state.evidenceStatus = event.target.value;
    state.evidenceLimit = PAGE_SIZE;
    renderEvidence();
  });
  $("evidence-search").addEventListener("input", (event) => {
    state.evidenceQuery = event.target.value;
    state.evidenceLimit = PAGE_SIZE;
    renderEvidence();
  });
  $("evidence-more").addEventListener("click", () => {
    const firstNew = state.evidenceLimit;
    state.evidenceLimit += PAGE_SIZE;
    renderEvidence();
    $("evidence-list").querySelectorAll("summary")[firstNew]?.focus();
  });
  $("event-select").addEventListener("change", (event) => {
    state.eventIndex = Number(event.target.value);
    state.eventLimit = PAGE_SIZE;
    renderEvents();
  });
  $("event-more").addEventListener("click", () => {
    const firstNew = state.eventLimit;
    state.eventLimit += PAGE_SIZE;
    renderEvents();
    $("event-changes").querySelectorAll("summary")[firstNew]?.focus();
  });
  window.addEventListener("resize", () => {
    updateExplorerPlacement();
    drawHistory();
  });
}

async function load() {
  $("dashboard").hidden = true;
  $("error-state").hidden = true;
  $("load-state").hidden = false;
  $("retry").disabled = true;
  state.data = null;
  setText("observed-at", "Not loaded");
  setText("observation-age", "This is a published snapshot, not a live view.");
  $("observation-age").classList.remove("is-stale");
  setText("source-status", "");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30_000);
  try {
    const response = await fetch("data.json", { cache: "no-store", signal: controller.signal });
    if (!response.ok) throw new Error(`The data request returned HTTP ${response.status}.`);
    let data;
    try {
      data = await response.json();
    } catch (error) {
      if (error.name === "AbortError") throw error;
      throw new Error("data.json is missing or is not valid JSON.");
    }
    state.data = validatePayload(data);
    state.months = 6;
    document.querySelector('input[name="window"][value="6"]').checked = true;
    state.chartsAvailable = chartLibraryAvailable();
    renderOverview();
    renderMethodology();
    chooseBenchmark("named");
    $("load-state").hidden = true;
    $("dashboard").hidden = false;
    updateExplorerPlacement();
    drawHistory();
    followSectionHash();
  } catch (error) {
    state.data = null;
    $("dashboard").hidden = true;
    $("load-state").hidden = true;
    $("error-state").hidden = false;
    setText("observed-at", "Data unavailable");
    setText("observation-age", "No validated observation is displayed.");
    setText("source-status", "");
    setText("error-message", error.name === "AbortError"
      ? "Loading data timed out. Check your connection and retry."
      : error instanceof DataValidationError ? `Data validation failed: ${error.message}`
        : error instanceof TypeError ? "Could not load the dashboard data. Check connectivity and serve this static site over HTTP, then retry."
          : error.message || "The coverage artifact could not be loaded.");
    console.error("Coverage dashboard initialization failed.", error);
  } finally {
    clearTimeout(timeout);
    $("retry").disabled = false;
  }
}

bindControls();
load();
