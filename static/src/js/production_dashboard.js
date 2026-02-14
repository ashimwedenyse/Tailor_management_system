/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";

export class TailorProductionDashboard extends Component {
  setup() {
    this.orm = useService("orm");
    this.action = useService("action");

    // ✅ Canvas refs (must match t-ref in XML)
    this.wipByMonthCanvas = useRef("wipByMonthCanvas");
    this.throughputByMonthCanvas = useRef("throughputByMonthCanvas");
    this.topTailorsWipCanvas = useRef("topTailorsWipCanvas");
    this.topTailorsDeliveredCanvas = useRef("topTailorsDeliveredCanvas");

    // ✅ Chart instances
    this._charts = {};

    // ✅ Cache meta for tailor.order fields
    this._orderMeta = null;

    // ✅ State
    this.state = useState({
      loading: true,
      data: {
        kpis: {},
        charts: {
          wip_by_month: [],
          throughput_by_month: [],
          top_tailors_wip: [],
          top_tailors_delivered: [],
        },
        tables: {},
        meta: {},
      },
      filters: {
        date_from: false,
        date_to: false,
        range: "7d", // today | 7d | 30d | custom
      },
      ui: {
        chart_view: {
          wip_by_month: "table",           // table | line | area | bar
          throughput_by_month: "table",    // table | line | bar
          top_tailors_wip: "table",        // table | bar
          top_tailors_delivered: "table",  // table | bar
        },
      },
    });

    onWillStart(async () => {
      await this._ensureChartJs();

      const r = this._computeRange(this.state.filters.range);
      if (r && this.state.filters.range !== "custom") {
        this.state.filters.date_from = r.from;
        this.state.filters.date_to = r.to;
      }

      await this._ensureOrderMeta();
      await this.load();
    });

    onMounted(() => {
      this._afterDOM(() => this.renderChartsSafe());
    });

    onWillUnmount(() => {
      this.destroyCharts();
    });
  }

  // =====================================================
  // ✅ DOM wait helper (safe)
  // =====================================================
  _afterDOM(cb) {
    requestAnimationFrame(() => requestAnimationFrame(cb));
  }

  // =====================================================
  // ✅ Ensure Chart.js exists (auto-load)
  // =====================================================
  async _ensureChartJs() {
    if (window.Chart) return;

    const candidates = [
      "/web/static/lib/Chart/Chart.js",
      "/web/static/lib/chartjs/chart.js",
      "/web/static/lib/chart.js/chart.js",
    ];

    for (const url of candidates) {
      try {
        await loadJS(url);
        if (window.Chart) return;
      } catch (e) {
        // try next
      }
    }
  }

  // =====================================================
  // Date helpers
  // =====================================================
  _formatDate(d) {
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd}`;
  }

  _computeRange(range) {
    const now = new Date();
    const end = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const start = new Date(end);

    if (range === "today") {
      // same day
    } else if (range === "7d") {
      start.setDate(start.getDate() - 6);
    } else if (range === "30d") {
      start.setDate(start.getDate() - 29);
    } else {
      return null; // custom
    }
    return { from: this._formatDate(start), to: this._formatDate(end) };
  }

  _todayISO() {
    try {
      const DateTime = window.luxon?.DateTime;
      if (DateTime) return DateTime.local().toISODate(); // "YYYY-MM-DD"
    } catch (e) {}
    return this._formatDate(new Date());
  }

  _todayStartEnd() {
    const day = this._todayISO();
    return {
      day,
      start: `${day} 00:00:00`,
      end: `${day} 23:59:59`,
    };
  }

  _and(domain, cond) {
    return ["&", cond, ...domain];
  }

  _pushDateFilterOnCreateDate(domain) {
    const df = this.state?.filters?.date_from;
    const dt = this.state?.filters?.date_to;
    if (df) domain = this._and(domain, ["create_date", ">=", `${df} 00:00:00`]);
    if (dt) domain = this._and(domain, ["create_date", "<=", `${dt} 23:59:59`]);
    return domain;
  }

  // =====================================================
  // ✅ Detect REAL fields + types on tailor.order
  // =====================================================
  async _ensureOrderMeta() {
    if (this._orderMeta) return this._orderMeta;

    const statusCandidates = ["status", "state", "stage", "x_status"];
    const deadlineCandidates = ["date_deadline", "deadline_date", "x_deadline", "commitment_date"];
    const deliveryCandidates = ["delivery_date", "x_delivery_date", "commitment_date"];

    const want = Array.from(new Set([...statusCandidates, ...deadlineCandidates, ...deliveryCandidates]));

    let defs = {};
    try {
      defs = await this.orm.call("tailor.order", "fields_get", [want, ["type"]]);
    } catch (e) {
      defs = {};
    }

    const pick = (cands) => {
      for (const f of cands) {
        if (defs && defs[f]) return { name: f, type: defs[f].type };
      }
      return { name: null, type: null };
    };

    const st = pick(statusCandidates);
    const dl = pick(deadlineCandidates);
    const dv = pick(deliveryCandidates);

    this._orderMeta = {
      statusField: st.name || "status",
      deadlineField: dl.name,
      deadlineType: dl.type, // date|datetime|null
      deliveryField: dv.name,
      deliveryType: dv.type,
    };
    return this._orderMeta;
  }

  // =====================================================
  // ✅ Build tokens
  // =====================================================
  _dueTodayTokens(field, type, start, end, day) {
    if (!field) return null;
    if (type === "datetime") return ["&", [field, ">=", start], [field, "<=", end]];
    return [field, "=", day]; // date
  }

  _overdueTokens(field, type, start, day) {
    if (!field) return null;
    if (type === "datetime") return [field, "<", start];
    return [field, "<", day];
  }

  // =====================================================
  // ✅ Load data
  // =====================================================
  async load() {
    this.state.loading = true;
    try {
      const res = await this.orm.call("tailor.production.dashboard", "get_kpis", [this.state.filters]);
      if (res) this.state.data = res;
    } catch (e) {
      // never crash
    } finally {
      this.state.loading = false;
      this._afterDOM(() => this.renderChartsSafe());
    }
  }

  async applyFilters() {
    await this.load();
  }

  // =====================================================
  // ✅ Navigation
  // =====================================================
  onGoDashboard(ev) {
    const target = ev?.currentTarget?.dataset?.target;
    if (!target) return;

    this.action.doAction({
      type: "ir.actions.client",
      tag: `tailor_${target}_dashboard`,
    });
  }

  onRangeClick(ev) {
    const range = ev?.currentTarget?.dataset?.range;
    if (!range) return;

    this.state.filters.range = range;

    if (range !== "custom") {
      const r = this._computeRange(range);
      if (r) {
        this.state.filters.date_from = r.from;
        this.state.filters.date_to = r.to;
      }
      this.applyFilters();
    }
  }

  onSetChartView(ev) {
    const key = ev?.currentTarget?.dataset?.key;
    const view = ev?.currentTarget?.dataset?.view;
    if (!key || !view) return;

    this.state.ui.chart_view[key] = view;
    this._afterDOM(() => this.renderChartsSafe());
  }

  // =====================================================
  // ✅✅ FIXED: Open stage in REAL Odoo Kanban view
  // =====================================================
  onOpenStage(ev) {
    const stage = ev?.currentTarget?.dataset?.stage;
    if (!stage) return;
    this.openKanbanStage(stage);
  }

  openKanbanStage(stage) {
    this.action.doAction({
      type: "ir.actions.act_window",
      name: "Tailor Orders",
      res_model: "tailor.order",
      views: [[false, "kanban"], [false, "list"], [false, "form"]], // ✅ kanban first
      view_mode: "kanban,list,form",                                // ✅ kanban first
      domain: [["status", "=", stage]],
      target: "current",
      context: {
        search_default_groupby_status: 1,
      },
    });
  }

  openWipManufacturing() {
    this.action.doAction({
      type: "ir.actions.act_window",
      name: "Manufacturing Orders (WIP)",
      res_model: "mrp.production",
      views: [[false, "list"], [false, "form"]],
      view_mode: "list,form",
      domain: [["state", "not in", ["done", "cancel"]]],
      target: "current",
    });
  }

  // =====================================================
  // ✅✅ Late Orders (Due Today) — FLAT domain
  // =====================================================
  async openLateOrders() {
    const meta = await this._ensureOrderMeta();
    const { day, start, end } = this._todayStartEnd();

    const statusField = meta.statusField || "status";
    const baseStatus = [statusField, "not in", ["delivered", "cancel"]];

    const dl = meta.deadlineField;
    const dv = meta.deliveryField;

    const dlDue = this._dueTodayTokens(dl, meta.deadlineType, start, end, day);
    const dvDue = this._dueTodayTokens(dv, meta.deliveryType, start, end, day);

    let domain;

    if (dl && dv && dlDue && dvDue) {
      domain = ["&", baseStatus,
        "|",
          "&", [dl, "!=", false], ...(dlDue[0] === "&" ? dlDue : [dlDue]),
          "&", [dl, "=", false],  ...(dvDue[0] === "&" ? dvDue : [dvDue]),
      ];
    } else if (dl && dlDue) {
      domain = ["&", baseStatus, ...(dlDue[0] === "&" ? dlDue : [dlDue])];
    } else if (dv && dvDue) {
      domain = ["&", baseStatus, ...(dvDue[0] === "&" ? dvDue : [dvDue])];
    } else {
      domain = [baseStatus];
    }

    domain = this._pushDateFilterOnCreateDate(domain);

    this.action.doAction({
      type: "ir.actions.act_window",
      name: "Late Orders (Due Today)",
      res_model: "tailor.order",
      views: [[false, "list"], [false, "form"]],
      view_mode: "list,form",
      domain,
      target: "current",
      context: { search_default_groupby_status: 1 },
    });
  }

  // =====================================================
  // ✅✅ Delayed Orders (Overdue) — FLAT domain
  // =====================================================
  async openDelayedOrders() {
    const meta = await this._ensureOrderMeta();
    const { day, start } = this._todayStartEnd();

    const statusField = meta.statusField || "status";
    const baseStatus = [statusField, "not in", ["delivered", "cancel"]];

    const dl = meta.deadlineField;
    const dv = meta.deliveryField;

    const dlOD = this._overdueTokens(dl, meta.deadlineType, start, day);
    const dvOD = this._overdueTokens(dv, meta.deliveryType, start, day);

    let domain;

    if (dl && dv && dlOD && dvOD) {
      domain = ["&", baseStatus,
        "|",
          "&", [dl, "!=", false], dlOD,
          "&", [dl, "=", false],  dvOD,
      ];
    } else if (dl && dlOD) {
      domain = ["&", baseStatus, dlOD];
    } else if (dv && dvOD) {
      domain = ["&", baseStatus, dvOD];
    } else {
      domain = [baseStatus];
    }

    domain = this._pushDateFilterOnCreateDate(domain);

    this.action.doAction({
      type: "ir.actions.act_window",
      name: "Delayed Orders (Overdue)",
      res_model: "tailor.order",
      views: [[false, "list"], [false, "form"]],
      view_mode: "list,form",
      domain,
      target: "current",
      context: { search_default_groupby_status: 1 },
    });
  }

  openStockAlerts() {
    this.action.doAction({
      type: "ir.actions.act_window",
      name: "Stock Alerts (Fabrics)",
      res_model: "product.product",
      views: [[false, "list"], [false, "form"]],
      view_mode: "list,form",
      domain: [],
      target: "current",
    });
  }

  // =====================================================
  // ✅ Charts
  // =====================================================
  renderChartsSafe() {
    try {
      this.renderCharts();
    } catch (e) {}
  }

  destroyCharts() {
    try {
      Object.values(this._charts || {}).forEach((ch) => {
        if (ch && typeof ch.destroy === "function") ch.destroy();
      });
    } catch (e) {}
    this._charts = {};
  }

  renderCharts() {
    const Chart = window.Chart;
    if (!Chart) return;

    const views = this.state.ui?.chart_view || {};
    const toNum = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0);

    this.destroyCharts();

    if (views.wip_by_month !== "table") {
      const el = this.wipByMonthCanvas?.el;
      if (el) {
        const rows = this.state.data.charts?.wip_by_month || [];
        const labels = rows.map((r) => r.label);
        const data = rows.map((r) => toNum(r.value));
        const type = views.wip_by_month === "bar" ? "bar" : "line";
        const fill = views.wip_by_month === "area";

        this._charts.wip_by_month = new Chart(el.getContext("2d"), {
          type,
          data: { labels, datasets: [{ label: "WIP Orders", data, fill, tension: 0.35 }] },
          options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
        });
      }
    }

    if (views.throughput_by_month !== "table") {
      const el = this.throughputByMonthCanvas?.el;
      if (el) {
        const rows = this.state.data.charts?.throughput_by_month || [];
        const labels = rows.map((r) => r.label);
        const data = rows.map((r) => toNum(r.value));
        const type = views.throughput_by_month === "bar" ? "bar" : "line";

        this._charts.throughput_by_month = new Chart(el.getContext("2d"), {
          type,
          data: { labels, datasets: [{ label: "Delivered Orders", data, fill: false, tension: 0.35 }] },
          options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
        });
      }
    }

    if (views.top_tailors_wip !== "table") {
      const el = this.topTailorsWipCanvas?.el;
      if (el) {
        const rows = this.state.data.charts?.top_tailors_wip || [];
        const labels = rows.map((r) => r.label);
        const data = rows.map((r) => toNum(r.value));

        this._charts.top_tailors_wip = new Chart(el.getContext("2d"), {
          type: "bar",
          data: { labels, datasets: [{ label: "WIP", data }] },
          options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
        });
      }
    }

    if (views.top_tailors_delivered !== "table") {
      const el = this.topTailorsDeliveredCanvas?.el;
      if (el) {
        const rows = this.state.data.charts?.top_tailors_delivered || [];
        const labels = rows.map((r) => r.label);
        const data = rows.map((r) => toNum(r.value));

        this._charts.top_tailors_delivered = new Chart(el.getContext("2d"), {
          type: "bar",
          data: { labels, datasets: [{ label: "Delivered", data }] },
          options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
        });
      }
    }
  }
}

TailorProductionDashboard.template = "tailor_management.TailorProductionDashboard";
registry.category("actions").add("tailor_production_dashboard", TailorProductionDashboard);
