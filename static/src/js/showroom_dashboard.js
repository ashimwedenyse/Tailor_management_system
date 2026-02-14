/** @odoo-module **/

import {
  Component,
  onWillStart,
  onMounted,
  onWillUnmount,
  useState,
  useRef,
} from "@odoo/owl";

import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { loadJS } from "@web/core/assets";

export class TailorShowroomDashboard extends Component {
  setup() {
    this.orm = useService("orm");
    this.actionService = useService("action");

    // ✅ Canvas refs (must match t-ref names in XML)
    this.salesPerfCanvas = useRef("salesPerfCanvas");
    this.ordersByStatusCanvas = useRef("ordersByStatusCanvas");
    this.ordersByMonthCanvas = useRef("ordersByMonthCanvas");
    this.revenueByMonthCanvas = useRef("revenueByMonthCanvas");

    this.state = useState({
      loading: true,
      filters: {
        date_from: false,
        date_to: false,
        range: "7d", // today | 7d | 30d | custom
      },
      data: {
        kpis: {},
        charts: {
          sales_performance: [],
          orders_by_status: [],
          orders_by_month: [],
          revenue_by_month: [],
          top_models: [],
        },
      },

      // ✅ NEW: chart view selection (used by pills)
      ui: {
        chart_view: {
          sales_performance: "table", // table | bar
          orders_by_status: "table",  // table | donut | bar
          orders_by_month: "table",   // table | line | bar
          revenue_by_month: "table",  // table | line | area
        },
      },
    });

    // ✅ store Chart.js instances
    this._chartInstances = {};

    onWillStart(async () => {
      await this._ensureChartJs();

      // ✅ set initial dates based on default range
      const init = this._computeRange(this.state.filters.range);
      if (init && this.state.filters.range !== "custom") {
        this.state.filters.date_from = init.from;
        this.state.filters.date_to = init.to;
      }
      await this.loadData();
    });

    onMounted(() => {
      // Render charts only if user switches away from table
      this._afterDOM(() => this.renderChartsSafe());
    });

    onWillUnmount(() => {
      this.destroyCharts();
    });

    // ✅ dashboard switch
    this.goDashboard = (name) => {
      const xmlids = {
        executive: "tailor_management.action_tailor_executive_dashboard",
        showroom: "tailor_management.action_tailor_showroom_dashboard",
        production: "tailor_management.action_tailor_production_dashboard",
      };
      const xmlid = xmlids[name];
      if (!xmlid) return;
      this.actionService.doAction(xmlid);
    };

    // =====================================================
    // ✅ Chart selector handler (called by XML pills)
    // =====================================================
    this.setChartView = (key, view) => {
      if (!this.state.ui || !this.state.ui.chart_view) return;
      this.state.ui.chart_view[key] = view;

      // ✅ wait for DOM to render canvas then draw
      this._afterDOM(() => this.renderChartsSafe());
    };

    // =====================================================
    // ✅ Range handling
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

    // =====================================================
    // ✅ Date domain for clicks
    // =====================================================
    this._dateDomain = () => {
      const df = this.state.filters.date_from;
      const dt = this.state.filters.date_to;
      const dom = [];
      if (df) dom.push(["date_order", ">=", `${df} 00:00:00`]);
      if (dt) dom.push(["date_order", "<=", `${dt} 23:59:59`]);
      return dom;
    };

    // ✅ open sales orders
    this.openSaleOrders = (domain) => {
      const finalDomain = [...this._dateDomain(), ...(domain || [])];

      this.actionService.doAction({
        type: "ir.actions.act_window",
        name: "Sales Orders",
        res_model: "sale.order",
        views: [[false, "list"], [false, "form"]],
        view_mode: "list,form",
        domain: finalDomain,
        target: "current",
      });
    };

    // ✅ missing docs
    this.openMissingDocs = () => {
      this.actionService.doAction({
        type: "ir.actions.act_window",
        name: "Missing Documents",
        res_model: "customer.documents",
        views: [[false, "list"], [false, "form"]],
        view_mode: "list,form",
        domain: [["is_missing", "=", true]],
        target: "current",
      });
    };

    // KPI click handlers
    this.openNewOrdersToday = () => {
      const t = new Date().toISOString().slice(0, 10);
      this.actionService.doAction({
        type: "ir.actions.act_window",
        name: "Sales Orders (Today)",
        res_model: "sale.order",
        views: [[false, "list"], [false, "form"]],
        view_mode: "list,form",
        domain: [
          ["create_date", ">=", `${t} 00:00:00`],
          ["create_date", "<=", `${t} 23:59:59`],
        ],
        target: "current",
      });
    };

    this.openPendingQuotations = () => {
      this.openSaleOrders([["state", "in", ["draft", "sent"]]]);
    };

    this.openDeliveredOrders = () => {
      this.openSaleOrders([["picking_ids.state", "=", "done"]]);
    };
  }

  // =====================================================
  // ✅ DOM wait helper (replaces nextTick)
  // Runs callback after Owl has updated the DOM.
  // =====================================================
  _afterDOM(cb) {
    // 2 frames is safer in Odoo because of nested renders
    requestAnimationFrame(() => requestAnimationFrame(cb));
  }

  // =====================================================
  // ✅ Ensure Chart.js exists (auto-load)
  // =====================================================
  async _ensureChartJs() {
    if (window.Chart) return;

    const candidates = [
      "/web/static/lib/Chart/Chart.js",     // common Odoo path
      "/web/static/lib/chartjs/chart.js",   // alt
      "/web/static/lib/chart.js/chart.js",  // alt
    ];

    for (const url of candidates) {
      try {
        await loadJS(url);
        if (window.Chart) return;
      } catch (e) {
        // try next
      }
    }
    // If still missing => charts will not draw, tables remain OK.
  }

  // ----------------------------
  // ✅ Helpers for range handling
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
      return null; // custom
    }
    return { from: this._formatDate(start), to: this._formatDate(end) };
  }

  // =====================================================
  // ✅ Chart render utils
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

    // destroy previous charts first
    this.destroyCharts();

    const toNum = (v) => {
      const n = Number(v);
      return Number.isFinite(n) ? n : 0;
    };

    // 1) Sales Performance (bar)
    if (views.sales_performance !== "table") {
      const el = this.salesPerfCanvas?.el;
      if (el) {
        const rows = this.state.data.charts.sales_performance || [];
        const labels = rows.map((r) => r.label);
        const data = rows.map((r) => toNum(r.value));

        this._chartInstances.sales_performance = new Chart(el.getContext("2d"), {
          type: "bar",
          data: { labels, datasets: [{ label: "Confirmed Sales", data }] },
          options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
        });
      }
    }

    // 2) Orders by Status (donut / bar)
    if (views.orders_by_status !== "table") {
      const el = this.ordersByStatusCanvas?.el;
      if (el) {
        const allowed = [
          // English
          "Draft",
          "Quotation",
          "Pending Quotations",
          "Confirmed",
          "Ready Delivery",
          "Ready for Delivery",
          "Delivered",
          "Cancelled",
          // Arabic (must match exactly what backend sends)
          "مسودة",
          "عرض سعر",
          "عروض أسعار معلقة",
          "مؤكد",
          "جاهز للتسليم",
          "تم التسليم",
          "ملغي",
          "تم الإلغاء",
        ];

        const rows = (this.state.data.charts.orders_by_status || []).filter((r) => allowed.includes(r.label));
        const labels = rows.map((r) => r.label);
        const data = rows.map((r) => toNum(r.value));

        const type = views.orders_by_status === "donut" ? "doughnut" : "bar";

        this._chartInstances.orders_by_status = new Chart(el.getContext("2d"), {
          type,
          data: { labels, datasets: [{ label: "Orders", data }] },
          options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: type === "doughnut" } } },
        });
      }
    }

    // 3) Orders by Month (line / bar)
    if (views.orders_by_month !== "table") {
      const el = this.ordersByMonthCanvas?.el;
      if (el) {
        const rows = this.state.data.charts.orders_by_month || [];
        const labels = rows.map((r) => r.label);
        const data = rows.map((r) => toNum(r.value));
        const type = views.orders_by_month === "bar" ? "bar" : "line";

        this._chartInstances.orders_by_month = new Chart(el.getContext("2d"), {
          type,
          data: { labels, datasets: [{ label: "Orders", data, fill: false }] },
          options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
        });
      }
    }

    // 4) Revenue by Month (line / area)
    if (views.revenue_by_month !== "table") {
      const el = this.revenueByMonthCanvas?.el;
      if (el) {
        const rows = this.state.data.charts.revenue_by_month || [];
        const labels = rows.map((r) => r.label);
        const data = rows.map((r) => toNum(r.value));
        const fillArea = views.revenue_by_month === "area";

        this._chartInstances.revenue_by_month = new Chart(el.getContext("2d"), {
          type: "line",
          data: { labels, datasets: [{ label: "Revenue", data, fill: fillArea }] },
          options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
        });
      }
    }
  }

  // =====================================================
  // Data loading
  // =====================================================
  async loadData() {
    this.state.loading = true;

    const res = await this.orm.call(
      "tailor.showroom.dashboard",
      "get_kpis",
      [this.state.filters.date_from, this.state.filters.date_to, false]
    );

    this.state.data = {
      kpis: (res && res.kpis) || {},
      charts: {
        sales_performance: (res && res.charts && res.charts.sales_performance) || [],
        orders_by_status: (res && res.charts && res.charts.orders_by_status) || [],
        orders_by_month: (res && res.charts && res.charts.orders_by_month) || [],
        revenue_by_month: (res && res.charts && res.charts.revenue_by_month) || [],
        top_models: (res && res.charts && res.charts.top_models) || [],
      },
    };

    this.state.loading = false;

    // ✅ render charts after DOM updates
    this._afterDOM(() => this.renderChartsSafe());
  }

  async applyFilters() {
    await this.loadData();
  }
}

TailorShowroomDashboard.template = "tailor_management.TailorShowroomDashboard";
registry.category("actions").add("tailor_showroom_dashboard", TailorShowroomDashboard);
