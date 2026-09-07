/* Animated dashboard of the historical undergraduate coverage of mathlib4. */
/* global d3 */

const PLAY_INTERVAL_MS = 700;

const els = {
  play: document.getElementById("play"),
  scrubber: document.getElementById("scrubber"),
  date: document.getElementById("current-date"),
  source: document.getElementById("current-source"),
  implemented: document.getElementById("stat-implemented"),
  external: document.getElementById("stat-external"),
  total: document.getElementById("stat-total"),
  percentage: document.getElementById("stat-percentage"),
  velocity: document.getElementById("stat-velocity"),
  acceleration: document.getElementById("stat-acceleration"),
  generated: document.getElementById("generated"),
};

const state = { data: null, index: 0, timer: null };

function formatNumber(value) {
  // Velocity and acceleration are undefined for the first snapshots, where
  // there is no previous month to compare against.
  if (value === null || value === undefined) return "—";
  return d3.format("+.2f")(value);
}

function renderStats(entry) {
  els.date.textContent = entry.date;
  els.source.textContent = entry.source;
  els.source.dataset.source = entry.source;
  els.implemented.textContent = entry.overall.implemented;
  els.external.textContent = entry.overall.external;
  els.total.textContent = entry.overall.total;
  els.percentage.textContent = `${entry.overall.percentage.toFixed(1)}%`;
  els.velocity.textContent = formatNumber(entry.metrics.velocity_per_month);
  els.acceleration.textContent = formatNumber(entry.metrics.acceleration);
}

function renderBars(entry, categories) {
  const svg = d3.select("#bars");
  const width = svg.node().clientWidth || 800;
  const margin = { top: 10, right: 60, bottom: 20, left: 170 };
  const height = Math.max(200, categories.length * 26 + margin.top + margin.bottom);
  svg.attr("height", height);

  const x = d3.scaleLinear([0, 100], [margin.left, width - margin.right]);
  const y = d3.scaleBand(categories, [margin.top, height - margin.bottom]).padding(0.2);

  let axis = svg.select("g.axis");
  if (axis.empty()) axis = svg.append("g").attr("class", "axis y-axis");
  axis.attr("transform", `translate(${margin.left},0)`).call(d3.axisLeft(y));

  const rows = svg.selectAll("g.row").data(categories, (d) => d);
  const enter = rows.enter().append("g").attr("class", "row");
  enter.append("rect").attr("class", "bar-bg");
  enter.append("rect").attr("class", "bar");
  enter.append("text").attr("class", "bar-label");

  const merged = enter.merge(rows);
  merged.select("rect.bar-bg")
    .attr("x", x(0))
    .attr("y", (d) => y(d))
    .attr("height", y.bandwidth())
    .attr("width", x(100) - x(0));
  merged.select("rect.bar")
    .attr("x", x(0))
    .attr("y", (d) => y(d))
    .attr("height", y.bandwidth())
    .transition().duration(400)
    .attr("width", (d) => x(entry.categories[d] ? entry.categories[d].percentage : 0) - x(0));
  merged.select("text.bar-label")
    .attr("y", (d) => y(d) + y.bandwidth() / 2 + 4)
    .transition().duration(400)
    .attr("x", (d) => x(entry.categories[d] ? entry.categories[d].percentage : 0) + 6)
    .textTween(function (d) {
      const value = entry.categories[d] ? entry.categories[d].percentage : 0;
      const previous = Number(this.textContent.replace("%", "")) || 0;
      const interpolate = d3.interpolateNumber(previous, value);
      return (t) => `${interpolate(t).toFixed(1)}%`;
    });

  rows.exit().remove();
}

function sourceTransitions(timeline) {
  // Indices where the underlying repository changes, e.g. the mathlib3 -> mathlib4 port.
  const marks = [];
  for (let i = 1; i < timeline.length; i += 1) {
    if (timeline[i].source !== timeline[i - 1].source) marks.push(timeline[i]);
  }
  return marks;
}

function renderLine(timeline, index) {
  const svg = d3.select("#line");
  const width = svg.node().clientWidth || 800;
  const height = 340;
  const margin = { top: 10, right: 20, bottom: 30, left: 45 };
  svg.attr("height", height);

  const parse = d3.utcParse("%Y-%m-%d");
  const points = timeline.map((entry) => ({ date: parse(entry.date), value: entry.overall.percentage }));
  const x = d3.scaleUtc(d3.extent(points, (p) => p.date), [margin.left, width - margin.right]);
  const y = d3.scaleLinear([0, Math.max(100, d3.max(points, (p) => p.value))], [height - margin.bottom, margin.top]);

  let group = svg.select("g.line-chart");
  if (group.empty()) {
    group = svg.append("g").attr("class", "line-chart");
    group.append("g").attr("class", "axis x-axis");
    group.append("g").attr("class", "axis y-axis");
    group.append("g").attr("class", "splices");
    group.append("path").attr("class", "line");
    group.append("circle").attr("class", "marker").attr("r", 5);
  }
  group.select("g.x-axis")
    .attr("transform", `translate(0,${height - margin.bottom})`)
    .call(d3.axisBottom(x));
  group.select("g.y-axis")
    .attr("transform", `translate(${margin.left},0)`)
    .call(d3.axisLeft(y).tickFormat((d) => `${d}%`));

  const splices = group.select("g.splices")
    .selectAll("g.splice")
    .data(sourceTransitions(timeline), (d) => d.date);
  const spliceEnter = splices.enter().append("g").attr("class", "splice");
  spliceEnter.append("line");
  spliceEnter.append("text");
  const spliceMerged = spliceEnter.merge(splices);
  spliceMerged.attr("transform", (d) => `translate(${x(parse(d.date))},0)`);
  spliceMerged.select("line")
    .attr("y1", margin.top)
    .attr("y2", height - margin.bottom);
  spliceMerged.select("text")
    .attr("y", margin.top + 12)
    .attr("dx", 5)
    .text((d) => `→ ${d.source}`);
  splices.exit().remove();

  const line = d3.line().x((p) => x(p.date)).y((p) => y(p.value));
  group.select("path.line").datum(points).attr("d", line);
  group.select("circle.marker")
    .transition().duration(400)
    .attr("cx", x(points[index].date))
    .attr("cy", y(points[index].value));
}

function show(index) {
  const timeline = state.data.timeline;
  state.index = ((index % timeline.length) + timeline.length) % timeline.length;
  els.scrubber.value = String(state.index);
  const entry = timeline[state.index];
  renderStats(entry);
  renderBars(entry, state.data.meta.categories);
  renderLine(timeline, state.index);
}

function stop() {
  if (state.timer !== null) {
    clearInterval(state.timer);
    state.timer = null;
  }
  els.play.textContent = "▶ Play";
}

function play() {
  stop();
  els.play.textContent = "⏸ Pause";
  state.timer = setInterval(() => show(state.index + 1), PLAY_INTERVAL_MS);
}

function describeSource(source) {
  return `${source.name} (${source.ref} at ${source.head}, ${source.head_date})`;
}

function init(data) {
  state.data = data;
  els.scrubber.max = String(data.timeline.length - 1);
  const sources = data.meta.sources || [];
  const read = sources.length ? sources.map(describeSource).join(" then ") : "unknown sources";
  els.generated.textContent =
    `${data.meta.total_snapshots} monthly snapshots from ${data.meta.history_starts}, ` +
    `stitched from the Git history of ${read}. Generated ${data.meta.generated_at}.`;
  els.scrubber.addEventListener("input", () => {
    stop();
    show(Number(els.scrubber.value));
  });
  els.play.addEventListener("click", () => (state.timer === null ? play() : stop()));
  window.addEventListener("resize", () => show(state.index));
  show(0);
  play();
}

d3.json("data.json")
  .then(init)
  .catch((error) => {
    console.error(error);
    els.date.textContent = "failed to load data.json";
  });
