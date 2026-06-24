// Charts only — tables are now React/TanStack. See src/components/tables/*.tsx.

const ACCENT = "#4ea1ff";
const PANEL = "#151b22";
const TEXT = "#d5dae0";
const MUTED = "#7d8693";

const CAT_COLORS = {
  code: "#4ade80",
  "datasets/models": "#facc15",
  academic: "#818cf8",
  reference: "#f472b6",
  vendor: "#fb923c",
  media: "#22d3ee",
  other: "#6b7280",
};

let chartJsPromise = null;
let chartsRendered = false;

function configureChartDefaults() {
  if (!window.Chart) return;
  Chart.defaults.color = MUTED;
  Chart.defaults.borderColor = "#2a3038";
}

function loadChartJs() {
  if (window.Chart) {
    configureChartDefaults();
    return Promise.resolve(window.Chart);
  }
  if (chartJsPromise) return chartJsPromise;
  chartJsPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js";
    script.async = true;
    script.onload = () => {
      configureChartDefaults();
      resolve(window.Chart);
    };
    script.onerror = reject;
    document.head.appendChild(script);
  });
  return chartJsPromise;
}

function readJson(id) {
  const el = document.getElementById(id);
  return el ? JSON.parse(el.textContent) : null;
}

// ---------- charts ----------

function renderHostsChart() {
  const data = readJson("data-hosts-bar") || [];
  const canvas = document.getElementById("chart-hosts");
  if (!canvas || data.length === 0) return;
  new Chart(canvas, {
    type: "bar",
    data: {
      labels: data.map((d) => d.host),
      datasets: [{ label: "papers citing", data: data.map((d) => d.papers), backgroundColor: ACCENT }],
    },
    options: {
      indexAxis: "y",
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { x: { ticks: { color: MUTED } }, y: { ticks: { color: TEXT, font: { size: 11 } } } },
    },
  });
}

function renderCategoriesChart() {
  const data = readJson("data-categories") || [];
  const canvas = document.getElementById("chart-categories");
  if (!canvas || data.length === 0) return;
  new Chart(canvas, {
    type: "doughnut",
    data: {
      labels: data.map((d) => `${d.category} (${d.edges})`),
      datasets: [
        {
          data: data.map((d) => d.edges),
          backgroundColor: data.map((d) => CAT_COLORS[d.category] || CAT_COLORS.other),
          borderColor: PANEL,
          borderWidth: 2,
        },
      ],
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { position: "right", labels: { color: TEXT, font: { size: 11 } } } },
    },
  });
}

function renderHistChart() {
  const data = readJson("data-hist") || [];
  const canvas = document.getElementById("chart-hist");
  if (!canvas || data.length === 0) return;
  new Chart(canvas, {
    type: "bar",
    data: {
      labels: data.map((d) => d.n_urls),
      datasets: [{ label: "# papers", data: data.map((d) => d.n_papers), backgroundColor: ACCENT }],
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { title: { display: true, text: "URLs per paper (clipped at 100)", color: MUTED }, ticks: { color: MUTED } },
        y: { title: { display: true, text: "papers", color: MUTED }, ticks: { color: MUTED } },
      },
    },
  });
}

const SERIES_COLORS = ["#4ea1ff", "#4ade80", "#facc15", "#f472b6", "#fb923c", "#22d3ee"];

function renderPapersPerYearChart() {
  const data = readJson("data-papers-per-year") || [];
  const canvas = document.getElementById("chart-papers-per-year");
  if (!canvas) return;
  new Chart(canvas, {
    type: "bar",
    data: {
      labels: data.map((d) => d.year),
      datasets: [{ label: "papers", data: data.map((d) => d.n), backgroundColor: ACCENT }],
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { x: { ticks: { color: MUTED } }, y: { ticks: { color: MUTED } } },
    },
  });
}

function renderCitesPerYearChart() {
  const t = readJson("data-temporal");
  const canvas = document.getElementById("chart-cites-per-year");
  if (!t || !canvas) return;
  const rows = (t.cites_per_year_by_year || []).filter((r) => r.year != null);
  if (rows.length === 0) return;
  new Chart(canvas, {
    type: "bar",
    data: {
      labels: rows.map((r) => r.year),
      datasets: [
        { label: "mean cites/yr", data: rows.map((r) => r.mean_cpy ?? 0), backgroundColor: "#4ade80" },
        { label: "p90 cites/yr", data: rows.map((r) => r.p90_cpy ?? 0), backgroundColor: "#facc15", type: "line", borderColor: "#facc15", fill: false, tension: 0.3, pointRadius: 3 },
      ],
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { position: "bottom", labels: { color: MUTED, font: { size: 11 } } } },
      scales: {
        x: { ticks: { color: MUTED } },
        y: { ticks: { color: MUTED }, beginAtZero: true },
      },
    },
  });
}

function renderCommunityYearsChart() {
  const t = readJson("data-temporal");
  const canvas = document.getElementById("chart-community-years");
  if (!t || !canvas) return;
  const years = Array.from(new Set(t.community_years.map((d) => d.year))).sort((a, b) => a - b);
  const cids = t.top_communities;
  // Build per-cid series aligned to `years`
  const datasets = cids.map((cid, idx) => {
    const byYear = Object.fromEntries(
      t.community_years.filter((d) => d.community_id === cid).map((d) => [d.year, d.n]),
    );
    return {
      label: `community ${cid}`,
      data: years.map((y) => byYear[y] || 0),
      backgroundColor: SERIES_COLORS[idx % SERIES_COLORS.length],
      borderColor: SERIES_COLORS[idx % SERIES_COLORS.length],
      fill: true,
      stack: "communities",
    };
  });
  new Chart(canvas, {
    type: "bar",
    data: { labels: years, datasets },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { position: "bottom", labels: { color: MUTED, font: { size: 11 } } } },
      scales: {
        x: { stacked: true, ticks: { color: MUTED } },
        y: { stacked: true, ticks: { color: MUTED } },
      },
    },
  });
}

// ---------- tables ----------

function wireFilter(inputId, tableId) {
  const input = document.getElementById(inputId);
  const table = document.getElementById(tableId);
  if (!input || !table) return;
  input.addEventListener("input", () => {
    const q = input.value.trim().toLowerCase();
    for (const tr of table.tBodies[0].rows) {
      tr.style.display = !q || tr.textContent.toLowerCase().includes(q) ? "" : "none";
    }
  });
}

function wireSort(tableId) {
  const table = document.getElementById(tableId);
  if (!table || !table.dataset.sortable) return;
  const ths = table.tHead.rows[0].cells;
  Array.from(ths).forEach((th, idx) => {
    if (!th.dataset.key) return;
    th.addEventListener("click", () => {
      const numeric = th.dataset.numeric !== undefined;
      const desc = !th.classList.contains("sort-desc");
      Array.from(ths).forEach((o) => o.classList.remove("sort-asc", "sort-desc"));
      th.classList.add(desc ? "sort-desc" : "sort-asc");
      const rows = Array.from(table.tBodies[0].rows);
      rows.sort((a, b) => {
        const av = a.cells[idx].textContent.trim();
        const bv = b.cells[idx].textContent.trim();
        let cmp;
        if (numeric) {
          cmp = parseFloat(av.replace(/,/g, "")) - parseFloat(bv.replace(/,/g, ""));
        } else {
          cmp = av.localeCompare(bv);
        }
        return desc ? -cmp : cmp;
      });
      const tb = table.tBodies[0];
      rows.forEach((r) => tb.appendChild(r));
    });
  });
}

// ---------- drilldowns ----------

let hostDrills = null;
let authorDrills = null;
let communityDrills = null;

async function loadHostDrills() {
  if (hostDrills) return hostDrills;
  const r = await fetch("/data/host_drilldowns.json");
  hostDrills = await r.json();
  return hostDrills;
}

async function loadAuthorDrills() {
  if (authorDrills) return authorDrills;
  const r = await fetch("/data/author_drilldowns.json");
  authorDrills = await r.json();
  return authorDrills;
}

async function loadCommunityDrills() {
  if (communityDrills) return communityDrills;
  const r = await fetch("/data/community_drilldowns.json");
  communityDrills = await r.json();
  return communityDrills;
}

function showHostDrilldown(host) {
  loadHostDrills().then((dd) => {
    const data = dd[host];
    const modal = document.getElementById("modal");
    const title = document.getElementById("modal-title");
    const body = document.getElementById("modal-body");
    title.textContent = `Papers citing ${host}`;
    if (!data || !data.citations || !data.citations.length) {
      body.innerHTML = `<p>No drilldown data for this host (only top 30 hosts are pre-rendered).</p>`;
    } else {
      body.innerHTML = data.citations
        .map(
          (c) => `
          <div class="row">
            <div class="url"><a href="${c.url_canonical}" target="_blank" rel="noopener">${c.url_canonical}</a></div>
            <div class="title">${c.title || ""}</div>
            <div class="meta">arxiv:${c.citing_arxiv_id} · ${c.citation_count != null ? c.citation_count.toLocaleString() + " citations" : ""}</div>
            ${c.context ? `<div class="ctx">"…${c.context}…"</div>` : ""}
          </div>`,
        )
        .join("");
    }
    modal.hidden = false;
  });
}

function showAuthorDrilldown(author) {
  loadAuthorDrills().then((dd) => {
    const data = dd[author];
    const modal = document.getElementById("modal");
    const title = document.getElementById("modal-title");
    const body = document.getElementById("modal-body");
    title.textContent = author;
    if (!data || !data.papers) {
      body.innerHTML = `<p>No drilldown for this author (only top 50 authors are pre-rendered).</p>`;
      modal.hidden = false;
      return;
    }
    const papersHtml = data.papers
      .map(
        (p) => `
        <div class="row">
          <div class="title">${p.title || ""}</div>
          <div class="meta">
            <a href="https://arxiv.org/abs/${p.arxiv_id}" target="_blank" rel="noopener">${p.arxiv_id}</a>
            · ${p.citation_count != null ? p.citation_count.toLocaleString() + " citations" : ""}
            · ${p.submitted_date ? p.submitted_date.slice(0, 7) : ""}
            ${p.community_id != null ? ` · community ${p.community_id}` : ""}
          </div>
        </div>`,
      )
      .join("");
    const hostsHtml = (data.top_hosts || [])
      .map((h) => `<span class="label-pill">${h.host} (${h.n})</span>`)
      .join(" ");
    const commsHtml = (data.communities || [])
      .map((c) => `<span class="label-pill">community ${c.community_id} (${c.n})</span>`)
      .join(" ");
    body.innerHTML = `
      <div class="row"><div class="meta">Top hosts cited across this author's papers:</div><div>${hostsHtml || "<em>(none)</em>"}</div></div>
      <div class="row"><div class="meta">Citation-graph communities this author appears in:</div><div>${commsHtml || "<em>(none)</em>"}</div></div>
      <div class="row"><div class="meta" style="margin-bottom:6px;">Papers (${data.papers.length}):</div>${papersHtml}</div>
    `;
    modal.hidden = false;
  });
}

function showCommunityDrilldown(cid) {
  loadCommunityDrills().then((dd) => {
    const data = dd[String(cid)];
    const modal = document.getElementById("modal");
    const title = document.getElementById("modal-title");
    const body = document.getElementById("modal-body");
    title.textContent = `Community ${cid}`;
    if (!data || !data.papers) {
      body.innerHTML = `<p>No drilldown for this community (only top 30 pre-rendered).</p>`;
      modal.hidden = false;
      return;
    }
    const hostsHtml = (data.top_hosts || [])
      .map((h) => `<span class="label-pill">${h.host} (${h.n})</span>`)
      .join(" ");
    const authorsHtml = (data.top_authors || [])
      .map((a) => `<span class="label-pill">${a.author} (${a.n})</span>`)
      .join(" ");
    const yrs = data.years || [];
    const ymin = yrs.length ? yrs[0].year : "";
    const ymax = yrs.length ? yrs[yrs.length - 1].year : "";
    const papersHtml = data.papers
      .map(
        (p) => `
        <div class="row">
          <div class="title">${p.title || ""}</div>
          <div class="meta">
            <a href="https://arxiv.org/abs/${p.arxiv_id}" target="_blank" rel="noopener">${p.arxiv_id}</a>
            · ${p.citation_count != null ? p.citation_count.toLocaleString() + " citations" : ""}
            · PR ${p.pagerank_score != null ? p.pagerank_score.toFixed(6) : ""}
            · ${p.submitted_date ? p.submitted_date.slice(0, 7) : ""}
          </div>
        </div>`,
      )
      .join("");
    body.innerHTML = `
      <div class="row"><div class="meta">Top hosts cited by this community:</div><div>${hostsHtml || "<em>(none)</em>"}</div></div>
      <div class="row"><div class="meta">Most prolific authors in this community:</div><div>${authorsHtml || "<em>(none)</em>"}</div></div>
      <div class="row"><div class="meta">Year range: ${ymin}–${ymax} (${yrs.length} years)</div></div>
      <div class="row"><div class="meta" style="margin-bottom:6px;">Top papers (by PageRank):</div>${papersHtml}</div>
    `;
    modal.hidden = false;
  });
}

function wireModals() {
  const modal = document.getElementById("modal");
  const close = document.getElementById("modal-close");

  document.querySelectorAll(".drill-btn").forEach((btn) => {
    if (btn.classList.contains("drill-author")) {
      btn.addEventListener("click", () => showAuthorDrilldown(btn.dataset.author));
    } else if (btn.classList.contains("drill-community")) {
      btn.addEventListener("click", () => showCommunityDrilldown(btn.dataset.communityId));
    } else {
      btn.addEventListener("click", () => showHostDrilldown(btn.dataset.host));
    }
  });
  if (!modal || !close) return;

  close.addEventListener("click", () => {
    modal.hidden = true;
  });
  modal.addEventListener("click", (e) => {
    if (e.target.id === "modal") modal.hidden = true;
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") modal.hidden = true;
  });
}

// ---------- boot ----------

function renderChartsOnce() {
  if (chartsRendered) return;
  chartsRendered = true;
  renderHostsChart();
  renderCategoriesChart();
  renderHistChart();
  renderPapersPerYearChart();
  renderCitesPerYearChart();
  renderCommunityYearsChart();
}

function bootCharts() {
  const canvases = Array.from(document.querySelectorAll("canvas[id^='chart-']"));
  if (canvases.length === 0) return;
  const loadAndRender = () => loadChartJs().then(renderChartsOnce).catch(() => {});
  if (!("IntersectionObserver" in window)) {
    window.requestIdleCallback ? window.requestIdleCallback(loadAndRender) : setTimeout(loadAndRender, 800);
    return;
  }
  const observer = new IntersectionObserver(
    (entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      observer.disconnect();
      loadAndRender();
    },
    { rootMargin: "500px 0px" },
  );
  canvases.forEach((canvas) => observer.observe(canvas));
}

document.addEventListener("DOMContentLoaded", () => {
  bootCharts();
  wireFilter("filter-hosts", "table-hosts");
  wireFilter("filter-urls", "table-urls");
  wireFilter("filter-papers", "table-papers");
  wireFilter("filter-cited", "table-cited");
  wireFilter("filter-cycles", "table-cycles");
  wireFilter("filter-communities", "table-communities");
  wireFilter("filter-authors", "table-authors");
  wireFilter("filter-abstracts", "table-abstracts");
  wireSort("table-authors");
  wireSort("table-hosts");
  wireSort("table-urls");
  wireSort("table-papers");
  wireSort("table-cited");
  wireModals();
});
