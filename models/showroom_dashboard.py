# -*- coding: utf-8 -*-
import logging
from datetime import datetime, date, timedelta

from odoo import api, fields, models
from odoo.tools import float_round

_logger = logging.getLogger(__name__)


class TailorShowroomDashboard(models.AbstractModel):
    _name = "tailor.showroom.dashboard"
    _description = "Showroom Dashboard RPC (Sales Orders Only)"

    # -----------------------------
    # Helpers
    # -----------------------------
    def _safe_month_label(self, month_val):
        if not month_val:
            return "Unknown"

        if isinstance(month_val, datetime):
            return month_val.date().strftime("%B %Y")
        if isinstance(month_val, date):
            return month_val.strftime("%B %Y")

        if isinstance(month_val, str):
            s = month_val.strip()
            try:
                d = fields.Date.from_string(s)
                if d:
                    return d.strftime("%B %Y")
            except Exception:
                pass
            return s

        return str(month_val)

    def _range_domain(self, date_from, date_to, field_name="date_order"):
        dom = []
        df = fields.Date.from_string(date_from) if date_from else False
        dt = fields.Date.from_string(date_to) if date_to else False
        if df:
            dom.append((field_name, ">=", fields.Datetime.to_datetime(df)))
        if dt:
            end_dt = fields.Datetime.to_datetime(dt) + timedelta(days=1) - timedelta(seconds=1)
            dom.append((field_name, "<=", end_dt))
        return dom

    # ------------------------------------------------------------
    # MAIN RPC
    # ------------------------------------------------------------
    @api.model
    def get_kpis(self, date_from=False, date_to=False, company_id=False):
        SaleOrder = self.env["sale.order"].sudo()
        SaleLine = self.env["sale.order.line"].sudo()
        CustomerDocs = self.env["customer.documents"].sudo()

        # ✅ ADDED: detect Arabic language for dashboard labels
        is_ar = (self.env.context.get("lang") or self.env.user.lang or "").startswith("ar")

        # ✅ ADDED: status labels mapping (EN/AR)
        STATUS_LABELS = {
            "draft": ("Draft", "مسودة"),
            "quotation": ("Quotation", "عرض سعر"),
            "confirmed": ("Confirmed", "مؤكد"),
            "ready_delivery": ("Ready for Delivery", "جاهز للتسليم"),
            "delivered": ("Delivered", "تم التسليم"),
            "cancelled": ("Cancelled", "ملغي"),
        }

        def _label(key):
            en, ar = STATUS_LABELS[key]
            return ar if is_ar else en

        # Domain for sales orders
        so_domain = self._range_domain(date_from, date_to, "date_order")
        if company_id:
            so_domain.append(("company_id", "=", int(company_id)))

        sale_orders = SaleOrder.search(so_domain)
        total_orders = len(sale_orders)

        # KPIs by state
        pending_quotations = SaleOrder.search_count(so_domain + [("state", "in", ("draft", "sent"))])
        confirmed_set = sale_orders.filtered(lambda o: o.state in ("sale", "done"))
        confirmed_orders = len(confirmed_set)
        cancelled_orders = SaleOrder.search_count(so_domain + [("state", "=", "cancel")])

        # Delivery KPIs (pickings)
        delivered_orders = SaleOrder.search_count(so_domain + [("picking_ids.state", "=", "done")])
        ready_delivery_orders = SaleOrder.search_count(so_domain + [("picking_ids.state", "=", "assigned")])

        # Today KPI
        today = fields.Date.context_today(self)
        today_start = fields.Datetime.to_datetime(today)
        today_end = today_start + timedelta(days=1) - timedelta(seconds=1)
        today_domain = [("date_order", ">=", today_start), ("date_order", "<=", today_end)]
        if company_id:
            today_domain.append(("company_id", "=", int(company_id)))
        new_orders_today = SaleOrder.search_count(today_domain)

        # Conversion
        total_quotations = SaleOrder.search_count(
            so_domain + [("state", "in", ("draft", "sent", "sale", "done"))]
        )
        showroom_conversion_rate = (confirmed_orders / total_quotations * 100.0) if total_quotations else 0.0

        # Revenue (confirmed orders)
        total_revenue = sum(o.amount_total for o in confirmed_set)
        total_vat = sum((o.amount_tax or 0.0) for o in confirmed_set)
        avg_order_value = (total_revenue / confirmed_orders) if confirmed_orders else 0.0

        # Balance Due (posted invoices residual linked to confirmed orders)
        total_balance_due = 0.0
        try:
            invs = confirmed_set.mapped("invoice_ids").filtered(
                lambda m: m.state == "posted" and m.move_type in ("out_invoice", "out_refund")
            )
            for inv in invs:
                if inv.move_type == "out_invoice":
                    total_balance_due += (inv.amount_residual or 0.0)
                else:
                    total_balance_due -= (inv.amount_residual or 0.0)
        except Exception:
            total_balance_due = 0.0

        # Missing docs
        missing_docs = 0
        try:
            if "sale_order_id" in CustomerDocs._fields and sale_orders:
                missing_docs = CustomerDocs.search_count([
                    ("sale_order_id", "in", sale_orders.ids),
                    ("is_missing", "=", True),
                ])
            else:
                missing_docs = CustomerDocs.search_count([("is_missing", "=", True)])
        except Exception:
            missing_docs = 0

        on_time_pct = 0.0

        # -----------------------------
        # Charts
        # -----------------------------

        # ✅ Sales performance by salesperson (confirmed) — reliable Python aggregation
        sales_map = {}
        for o in confirmed_set:
            key = o.user_id.id if o.user_id else 0
            label = o.user_id.name if o.user_id else "Unknown"
            sales_map.setdefault(key, {"label": label, "value": 0.0})
            sales_map[key]["value"] += (o.amount_total or 0.0)

        sales_performance = [
            {"label": v["label"], "value": float_round(v["value"], 2)}
            for v in sales_map.values()
        ]
        sales_performance.sort(key=lambda x: x["value"], reverse=True)

        # ✅ Orders by status (UPDATED to Arabic/English automatically)
        orders_by_status = [
            {
                "key": "draft",
                "label": _label("draft"),
                "value": SaleOrder.search_count(so_domain + [("state", "=", "draft")]),
            },
            {
                "key": "quotation",
                "label": _label("quotation"),
                "value": pending_quotations,
            },
            {
                "key": "confirmed",
                "label": _label("confirmed"),
                "value": confirmed_orders,
            },
            {
                "key": "ready_delivery",
                "label": _label("ready_delivery"),
                "value": ready_delivery_orders,
            },
            {
                "key": "delivered",
                "label": _label("delivered"),
                "value": delivered_orders,
            },
            {
                "key": "cancelled",
                "label": _label("cancelled"),
                "value": cancelled_orders,
            },
        ]

        # ✅ Orders trend by month (works across Odoo versions)
        orders_by_month = []
        rg_mo = SaleOrder.read_group(
            so_domain,
            ["id:count"],
            ["date_order:month"],
            lazy=False,
        )
        for r in rg_mo:
            count_val = r.get("id_count", r.get("__count", 0))
            orders_by_month.append({
                "label": self._safe_month_label(r.get("date_order:month")),
                "value": count_val,
            })

        # ✅ Revenue trend by month (ORDER-BASED) — Option 1
        rev_map = {}
        for o in confirmed_set:
            if not o.date_order:
                continue
            dt = fields.Datetime.to_datetime(o.date_order)
            key = (dt.year, dt.month)
            rev_map[key] = rev_map.get(key, 0.0) + (o.amount_total or 0.0)

        revenue_by_month = []
        for (yy, mm) in sorted(rev_map.keys()):
            month_date = date(yy, mm, 1)
            revenue_by_month.append({
                "label": month_date.strftime("%B %Y"),
                "value": float_round(rev_map[(yy, mm)], 2),
            })

        # ✅ Top Models (Qty) — Product-based (FIXED WITHOUT CHANGING ANYTHING ELSE)
        top_models = []

        # 1) Prefer confirmed orders; if none, fall back to all sale_orders so chart isn't blank
        base_orders = confirmed_set if confirmed_set else sale_orders

        if base_orders:
            line_domain = [("order_id", "in", base_orders.ids)]

            # exclude section/note lines if field exists
            if "display_type" in SaleLine._fields:
                line_domain.append(("display_type", "=", False))
            # exclude downpayment lines if field exists
            if "is_downpayment" in SaleLine._fields:
                line_domain.append(("is_downpayment", "=", False))

            # IMPORTANT: must have product_id for Top Models
            line_domain.append(("product_id", "!=", False))

            rg_models = SaleLine.read_group(
                line_domain,
                ["product_uom_qty:sum"],
                ["product_id"],
                lazy=False,
            )

            # Some Odoo builds use slightly different sum keys; handle all safely
            cleaned = []
            for x in (rg_models or []):
                if not x.get("product_id"):
                    continue
                qty_sum = (
                    x.get("product_uom_qty_sum")
                    or x.get("product_uom_qty")
                    or x.get("product_uom_qty:sum")
                    or 0.0
                )
                if (qty_sum or 0.0) <= 0:
                    continue
                x["_qty_sum"] = qty_sum
                cleaned.append(x)

            cleaned = sorted(cleaned, key=lambda x: x.get("_qty_sum", 0.0), reverse=True)[:10]

            for r in cleaned:
                name = r["product_id"][1]
                qty = float_round(r.get("_qty_sum", 0.0) or 0.0, 2)
                # Return both (label/value) and (name/qty) to avoid frontend mismatch
                top_models.append({
                    "label": name,
                    "value": qty,
                    "name": name,
                    "qty": qty,
                })

        # If still empty, show helpful message instead of blank widget
        if not top_models:
            top_models = [{
                "label": "No Products Found in Order Lines",
                "value": 0,
                "name": "No Products Found in Order Lines",
                "qty": 0,
            }]

        return {
            "kpis": {
                "new_orders_today": new_orders_today,
                "total_orders": total_orders,
                "pending_quotations": pending_quotations,
                "confirmed_orders": confirmed_orders,
                "ready_delivery_orders": ready_delivery_orders,
                "delivered_orders": delivered_orders,
                "cancelled_orders": cancelled_orders,
                "on_time_pct": float_round(on_time_pct, 2),
                "showroom_conversion_rate": float_round(showroom_conversion_rate, 2),
                "avg_order_value": float_round(avg_order_value, 2),
                "total_revenue": float_round(total_revenue, 2),
                "total_vat": float_round(total_vat, 2),
                "total_balance_due": float_round(total_balance_due, 2),
                "missing_docs": missing_docs,
            },
            "charts": {
                "sales_performance": sales_performance,
                "orders_by_status": orders_by_status,
                "orders_by_month": orders_by_month,
                "revenue_by_month": revenue_by_month,
                "top_models": top_models,
            },
        }
