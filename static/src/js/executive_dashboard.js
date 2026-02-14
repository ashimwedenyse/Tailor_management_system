/** @odoo-module **/

import { registry } from "@web/core/registry";
import {
  Component,
  useState,
  onWillStart,
  onMounted,
  onWillUnmount,
  useRef,
} from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";

class TailorExecutiveDashboard extends Component {
  setup() {
    this.orm = useService("orm");
    this.action = useService("action");

    // ✅ Canvas refs (must match t-ref names in Executive XML)
    this.ordersByStatusCanvas = useRef("ordersByStatusCanvas");
    this.ordersByMonthCanvas = useRef("ordersByMonthCanvas");
    this.revenueByMonthCanvas = useRef("revenueByMonthCanvas");
    this.salesPerfCanvas = useRef("salesPerfCanvas");
    this.revCostProfitCanvas = useRef("revCostProfitCanvas");

    // ✅ NEW refs (added for more chart places)
    this.topTailorsCanvas = useRef("topTailorsCanvas");
    this.topModelsCanvas = useRef("topModelsCanvas");
    this.topFabricsCanvas = useRef("topFabricsCanvas");
    this.missingDocsTypeCanvas = useRef("missingDocsTypeCanvas");

    this.state = useState({
      loading: true,
      data: { kpis: {}, charts: {}, filters: { date_from: false, date_to: false, company_id: false } },

      filters: {
        date_from: false,
        date_to: false,
        company_id: false,
        range: "7d",      // today | 7d | 30d | custom
        tailor_id: false, // id or false
        status: false,    // string or false
      },

      tailors: [],

      // ✅ chart view selection (table vs chart types)
      ui: {
        chart_view: {
          orders_by_status: "table",         // table | donut | bar
          orders_by_month: "table",          // table | line | bar
          revenue_by_month: "table",         // table | line | area
          sales_performance: "table",        // table | bar
          rev_cost_profit_by_month: "table", // table | line

          // ✅ NEW (for many places)
          top_tailors: "table",              // table | bar
          top_models: "table",               // table | bar
          top_fabrics: "table",              // table | bar
          missing_docs_by_type: "table",     // table | bar
        },
      },
    });

    // ✅ Chart instances
    this._chartInstances = {};

    // ✅ dashboard switch
    this.goDashboard = (which) => {
      const map = {
        executive: "tailor_management.action_tailor_executive_dashboard",
        showroom: "tailor_management.action_tailor_showroom_dashboard",
        production: "tailor_management.action_tailor_production_dashboard",
      };
      const xmlid = map[which];
      if (xmlid) this.action.doAction(xmlid);
    };

    // ✅ open orders
    this.openOrders = (domain) => {
      this.action.doAction({
        type: "ir.actions.act_window",
        name: "Tailor Orders",
        res_model: "tailor.order",
        views: [[false, "list"], [false, "form"]],
        view_mode: "list,form",
        domain: domain || [],
        target: "current",
      });
    };

    // ✅ open missing docs
    this.openMissingDocs = () => {
      this.action.doAction({
        type: "ir.actions.act_window",
        name: "Customer Documents",
        res_model: "customer.documents",
        views: [[false, "list"], [false, "form"]],
        view_mode: "list,form",
        domain: [["is_missing", "=", true]],
        target: "current",
      });
    };

    // ✅ topbar buttons
    this.openCustomers = () => {
      this.action.doAction({
        type: "ir.actions.act_window",
        name: "Customers",
        res_model: "res.partner",
        views: [[false, "list"], [false, "form"]],
        view_mode: "list,form",
        domain: [["customer_rank", ">", 0]],
        target: "current",
      });
    };

    this.openOrdersHome = () => this.openOrders([]);

    this.openReports = () => {
      this.action.doAction({
        type: "ir.actions.act_window",
        name: "Tailor Orders Analysis",
        res_model: "tailor.order",
        views: [[false, "pivot"], [false, "graph"], [false, "list"], [false, "form"]],
        view_mode: "pivot,graph,list,form",
        domain: [],
        target: "current",
      });
    };

    // =====================================================
    // ✅ FILTER BAR METHODS
    // =====================================================
    this.setRange = (range) => {
      this.state.filters.range = range;

      if (range !== "custom") {
        const r = this._computeRange(range);
        if (r) {
          this.state.filters.date_from = r.from;
          this.state.filters.date_to = r.to;
        }
        this.applyFilters();
      }
    };

    this.onTailorChange = (ev) => {
      const v = ev?.target?.value || "";
      this.state.filters.tailor_id = v ? Number(v) : false;
      this.applyFilters();
    };

    this.onStatusChange = (ev) => {
      const v = ev?.target?.value || "";
      this.state.filters.status = v ? v : false;
      this.applyFilters();
    };

    this.refresh = () => this.load();

    // =====================================================
    // ✅ Chart selector handler (for pills)
    // =====================================================
    this.setChartView = (key, view) => {
      if (!this.state.ui || !this.state.ui.chart_view) return;
      this.state.ui.chart_view[key] = view;
      this._afterDOM(() => this.renderChartsSafe());
    };

    onWillStart(async () => {
      await this._ensureChartJs();
      await this._loadTailors();

      this.state.filters.range = this.state.filters.range || "7d";
      const init = this._computeRange(this.state.filters.range);
      if (init && this.state.filters.range !== "custom") {
        this.state.filters.date_from = init.from;
        this.state.filters.date_to = init.to;
      }

      await this.load();
    });

    onMounted(() => {
      this._afterDOM(() => this.renderChartsSafe());
    });

    onWillUnmount(() => {
      this.destroyCharts();
    });
  }

  // ✅ DOM wait helper (no nextTick)
  _afterDOM(cb) {
    requestAnimationFrame(() => requestAnimationFrame(cb));
  }

  // ✅ Auto-load Chart.js
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

  // ✅ Normalize data
  _normalizeDashboardData(res) {
    const data = res || {};
    data.kpis = data.kpis || {};
    data.charts = data.charts || {};
    data.filters = data.filters || {};

    const ensureArray = (key) => {
      if (!Array.isArray(data.charts[key])) data.charts[key] = [];
    };

    ensureArray("orders_by_status");
    ensureArray("orders_by_month");
    ensureArray("revenue_by_month");
    ensureArray("top_tailors");
    ensureArray("missing_docs_by_type");
    ensureArray("sales_performance");
    ensureArray("top_models");
    ensureArray("top_fabrics");
    ensureArray("rev_cost_profit_by_month");

    return data;
  }

  // ----------------------------
  // ✅ Range helpers
  // ----------------------------
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
      return null;
    }
    return { from: this._formatDate(start), to: this._formatDate(end) };
  }

  // ----------------------------
  // ✅ Load Tailors
  // ----------------------------
  async _loadTailors() {
    const users = await this.orm.searchRead("res.users", [], ["name"], { limit: 200 });
    this.state.tailors = users || [];
  }

  // =====================================================
  // ✅ Chart helpers
  // =====================================================
  renderChartsSafe() {
    try {
      this.renderCharts();
    } catch (e) {
      // never break dashboard
    }
  }

  destroyCharts() {
    try {
      Object.values(this._chartInstances || {}).forEach((ch) => {
        if (ch && typeof ch.destroy === "function") ch.destroy();
      });
    } catch (e) {}
    this._chartInstances = {};
  }

  renderCharts() {
    const Chart = window.Chart;
    if (!Chart) return;

    const views = this.state.ui?.chart_view || {};
    const charts = this.state.data?.charts || {};

    this.destroyCharts();

    const toNum = (v) => {
      const n = Number(v);
      return Number.isFinite(n) ? n : 0;
    };

    const buildBar = (canvasRef, rows, label) => {
      const el = canvasRef?.el;
      if (!el) return;
      const labels = (rows || []).map((r) => r.label);
      const data = (rows || []).map((r) => toNum(r.value));
      this._chartInstances[label] = new Chart(el.getContext("2d"), {
        type: "bar",
        data: { labels, datasets: [{ label, data }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
      });
    };

    // Orders by Status
    if (views.orders_by_status !== "table") {
      const el = this.ordersByStatusCanvas?.el;
      if (el) {
        const rows = charts.orders_by_status || [];
        const labels = rows.map((r) => r.label);
        const data = rows.map((r) => toNum(r.value));
        const type = (views.orders_by_status === "donut") ? "doughnut" : "bar";

        this._chartInstances.orders_by_status = new Chart(el.getContext("2d"), {
          type,
          data: { labels, datasets: [{ label: "Orders", data }] },
          options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: type === "doughnut" } } },
        });
      }
    }

    // Orders by Month
    if (views.orders_by_month !== "table") {
      const el = this.ordersByMonthCanvas?.el;
      if (el) {
        const rows = charts.orders_by_month || [];
        const labels = rows.map((r) => r.label);
        const data = rows.map((r) => toNum(r.value));
        const type = (views.orders_by_month === "bar") ? "bar" : "line";

        this._chartInstances.orders_by_month = new Chart(el.getContext("2d"), {
          type,
          data: {
            labels,
            datasets: [{
              label: "Orders",
              data,
              fill: false,
              tension: 0.35,
              borderWidth: 2,
              pointRadius: 2,
              pointHoverRadius: 4,
              backgroundColor: "rgba(0,0,0,0)",
            }],
          },
          options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
        });
      }
    }

    // Revenue by Month (line/area)
    if (views.revenue_by_month !== "table") {
      const el = this.revenueByMonthCanvas?.el;
      if (el) {
        const rows = charts.revenue_by_month || [];
        const labels = rows.map((r) => r.label);
        const data = rows.map((r) => toNum(r.value));
        const isArea = views.revenue_by_month === "area";

        this._chartInstances.revenue_by_month = new Chart(el.getContext("2d"), {
          type: "line",
          data: {
            labels,
            datasets: [{
              label: "Revenue",
              data,
              fill: isArea ? "origin" : false,
              tension: 0.35,
              borderWidth: 2,
              pointRadius: 2,
              pointHoverRadius: 4,
              backgroundColor: isArea ? "rgba(13,110,253,0.18)" : "rgba(0,0,0,0)",
            }],
          },
          options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
        });
      }
    }

    // Sales Performance (bar)
    if (views.sales_performance !== "table") {
      buildBar(this.salesPerfCanvas, charts.sales_performance || [], "Sales");
    }

    // Revenue/Cost/Profit by Month
    if (views.rev_cost_profit_by_month !== "table") {
      const el = this.revCostProfitCanvas?.el;
      if (el) {
        const rows = charts.rev_cost_profit_by_month || [];
        const labels = rows.map((r) => r.label);

        const rev = rows.map((r) => toNum(r.revenue ?? r.rev ?? r.value ?? 0));
        const cost = rows.map((r) => toNum(r.fabric_cost ?? r.cost ?? 0));
        const profit = rows.map((r) => toNum(r.profit ?? 0));

        this._chartInstances.rev_cost_profit_by_month = new Chart(el.getContext("2d"), {
          type: "line",
          data: {
            labels,
            datasets: [
              { label: "Revenue", data: rev, fill: false, tension: 0.35, borderWidth: 2 },
              { label: "Fabric Cost", data: cost, fill: false, tension: 0.35, borderWidth: 2 },
              { label: "Profit", data: profit, fill: false, tension: 0.35, borderWidth: 2 },
            ],
          },
          options: { responsive: true, maintainAspectRatio: false },
        });
      }
    }

    // ✅ NEW: Top Tailors (bar)
    if (views.top_tailors !== "table") {
      buildBar(this.topTailorsCanvas, charts.top_tailors || [], "Top Tailors");
    }

    // ✅ NEW: Top Models (bar)
    if (views.top_models !== "table") {
      buildBar(this.topModelsCanvas, charts.top_models || [], "Top Models");
    }

    // ✅ NEW: Top Fabrics (bar)
    if (views.top_fabrics !== "table") {
      buildBar(this.topFabricsCanvas, charts.top_fabrics || [], "Top Fabrics");
    }

    // ✅ NEW: Missing Docs by Type (bar)
    if (views.missing_docs_by_type !== "table") {
      buildBar(this.missingDocsTypeCanvas, charts.missing_docs_by_type || [], "Missing Docs");
    }
  }

  async load() {
    this.state.loading = true;

    const res = await this.orm.call(
      "tailor.executive.dashboard",
      "get_kpis",
      [],
      {
        date_from: this.state.filters.date_from,
        date_to: this.state.filters.date_to,
        company_id: this.state.filters.company_id,
        tailor_id: this.state.filters.tailor_id,
        status: this.state.filters.status,
        range: this.state.filters.range,
      }
    );

    const data = this._normalizeDashboardData(res);
    this.state.data = data;

    if (data.filters) {
      this.state.filters.date_from = data.filters.date_from || this.state.filters.date_from || false;
      this.state.filters.date_to = data.filters.date_to || this.state.filters.date_to || false;
      this.state.filters.company_id = data.filters.company_id || this.state.filters.company_id || false;
    }

    this.state.loading = false;

    this._afterDOM(() => this.renderChartsSafe());
  }

  async applyFilters() {
    await this.load();
  }
}

TailorExecutiveDashboard.template = "tailor_management.TailorExecutiveDashboard";
registry.category("actions").add("tailor_executive_dashboard", TailorExecutiveDashboard);
