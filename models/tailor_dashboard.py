# -*- coding: utf-8 -*-
from collections import defaultdict
from datetime import timedelta

from odoo import models, api, fields


class TailorExecutiveDashboard(models.AbstractModel):
    _name = "tailor.executive.dashboard"
    _description = "Tailor Executive Dashboard (KPIs)"

    # ✅ ADDED: accept tailor_id/status/range (so RPC won't crash)
    @api.model
    def get_kpis(self, date_from=False, date_to=False, company_id=False, tailor_id=False, status=False, range=False):
        domain = []
        dom_docs = []
        dom_sale = []



        if company_id:
            domain += [("company_id", "=", int(company_id))]
            dom_sale += [("company_id", "=", int(company_id))]

        if date_from:
            domain += [("order_date", ">=", date_from)]
            dom_docs += [("create_date", ">=", date_from)]
            dom_sale += [("date_order", ">=", date_from)]

        if date_to:
            domain += [("order_date", "<=", date_to + " 23:59:59")]
            dom_docs += [("create_date", "<=", date_to + " 23:59:59")]
            dom_sale += [("date_order", "<=", date_to + " 23:59:59")]

        # ✅ ADDED: Tailor filter (affects orders + docs + revenue through sale_ids)
        if tailor_id:
            domain += [("tailor_id", "=", int(tailor_id))]

        # ✅ ADDED: Status filter (optional)
        # Important: this will narrow "orders" list, so "active/delivered/etc" become within that status.
        # If you want status dropdown to affect only charts but not "Active Orders", tell me and I adjust.
        if status:
            domain += [("status", "=", status)]
        lang = self.env.context.get("lang") or self.env.user.lang or "ar_001"

        TailorOrder = self.env["tailor.order"].sudo().with_context(lang=lang)
        Docs = self.env["customer.documents"].sudo().with_context(lang=lang)
        Sale = self.env["sale.order"].sudo().with_context(lang=lang)

        orders = TailorOrder.search(domain)

        total_orders = len(orders)
        delivered = orders.filtered(lambda o: o.status == "delivered")
        cancelled = orders.filtered(lambda o: o.status == "cancel")

        active = orders.filtered(lambda o: o.status in (
            "confirmed", "cutting", "sewing", "qc", "ready_delivery",
        ))

        qc = orders.filtered(lambda o: o.status == "qc")
        ready_delivery = orders.filtered(lambda o: o.status == "ready_delivery")

        # On-time delivery %
        on_time_count = 0
        for o in delivered:
            if o.delivery_date and o.status_changed_on and o.status_changed_on <= o.delivery_date:
                on_time_count += 1
        on_time_pct = (on_time_count / len(delivered) * 100.0) if delivered else 0.0

        # Avg lead time days
        lead_days = []
        for o in delivered:
            if o.order_date and o.status_changed_on:
                delta = o.status_changed_on - o.order_date
                lead_days.append(delta.total_seconds() / 86400.0)
        avg_lead_days = (sum(lead_days) / len(lead_days)) if lead_days else 0.0

        # Sale Orders revenue
        sale_ids = orders.mapped("sale_order_id").ids
        sale_domain = [("id", "in", sale_ids)] + dom_sale if sale_ids else [("id", "=", 0)]
        sale_recs = Sale.search(sale_domain)
        total_revenue = sum(sale_recs.mapped("amount_total")) if sale_recs else 0.0

        # -------------------------------------------------
        # ✅ SHOWROOM KPIs (Sale Order based)
        # -------------------------------------------------
        today = fields.Date.context_today(self)
        today_start = fields.Datetime.to_datetime(today)
        today_end = today_start + timedelta(days=1) - timedelta(seconds=1)

        # New Orders Today (Sale Orders)
        new_orders_today = Sale.search_count(dom_sale + [
            ("date_order", ">=", today_start),
            ("date_order", "<=", today_end),
        ])

        # Pending Quotations (draft + sent)
        pending_quotations = Sale.search_count(dom_sale + [
            ("state", "in", ("draft", "sent")),
        ])

        # Conversion Rate (Confirmed / Total Quotations) * 100
        total_quotations = Sale.search_count(dom_sale + [
            ("state", "in", ("draft", "sent", "sale", "done")),
        ])
        confirmed_sale_orders = Sale.search_count(dom_sale + [
            ("state", "in", ("sale", "done")),
        ])
        showroom_conversion_rate = (confirmed_sale_orders / total_quotations * 100.0) if total_quotations else 0.0

        # Sales performance (sum amount_total grouped by user_id)
        rg_sales_perf = Sale.read_group(
            dom_sale + [("state", "in", ("sale", "done"))],
            ["amount_total:sum"],
            ["user_id"],
            lazy=False,
        )
        sales_performance = []
        for r in rg_sales_perf:
            sp = r.get("user_id")
            sales_performance.append({
                "label": sp[1] if sp else "Unknown",
                "value": round(r.get("amount_total_sum") or 0.0, 2),
            })

        total_vat = sum(orders.mapped("vat_amount")) if orders else 0.0
        total_balance_due = sum(orders.mapped("balance")) if orders else 0.0

        # Missing docs
        doc_domain = [("is_missing", "=", True)] + dom_docs
        if orders:
            doc_domain = [("tailor_order_id", "in", orders.ids), ("is_missing", "=", True)]
            if dom_docs:
                doc_domain += dom_docs
        missing_docs_count = Docs.search_count(doc_domain)

        # QC pass rate
        qc_pass = delivered.filtered(lambda o: bool(o.qc_approved))
        qc_pass_rate = (len(qc_pass) / len(delivered) * 100.0) if delivered else 0.0

        # Accessories qty
        accessory_qty = 0.0
        for o in orders:
            for line in o.accessory_line_ids:
                accessory_qty += float(line.quantity or 0.0)

        # Fabric meters
        fabric_m = sum(orders.mapped("fabric_qty")) if orders else 0.0

        # ✅ Profitability (uses YOUR field: fabric_total_cost)
        fabric_cost_total = sum(orders.mapped("fabric_total_cost")) if orders else 0.0
        gross_profit = total_revenue - fabric_cost_total
        profit_margin_pct = (gross_profit / total_revenue * 100.0) if total_revenue else 0.0
        avg_order_value = (total_revenue / total_orders) if total_orders else 0.0

        # ----------------------------
        # Charts helpers
        # ----------------------------
        # Charts helpers (✅ translated labels based on user language)
        status_map = dict(
            self.env["tailor.order"]
            .with_context(lang=self.env.user.lang)
            .fields_get(["status"])["status"]["selection"]
        )

        by_status = []
        for key, label in status_map.items():
            cnt = len(orders.filtered(lambda o, k=key: o.status == k))
            by_status.append({"label": label, "value": cnt, "key": key})

        def _safe_month_label(val):
            if not val:
                return self.env._("Unknown")

            if isinstance(val, str):
                return val
            try:
                return fields.Date.to_string(val)
            except Exception:
                return str(val)

        def _rg_count(row):
            return row.get("__count") or row.get("id_count") or 0

        # Orders trend
        order_trend = TailorOrder.read_group(domain, ["id:count"], ["order_date:month"], lazy=False)
        orders_by_month = []
        for row in order_trend:
            orders_by_month.append({
                "label": _safe_month_label(row.get("order_date:month")),
                "value": _rg_count(row),
            })

        # Revenue trend
        revenue_by_month = []
        if sale_recs:
            sale_trend = Sale.read_group(sale_domain, ["amount_total:sum"], ["date_order:month"], lazy=False)
            for row in sale_trend:
                month_val = row.get("date_order:month")
                amount = row.get("amount_total_sum") or 0.0
                revenue_by_month.append({"label": _safe_month_label(month_val), "value": amount})

        # Top Tailors
        top_tailors = TailorOrder.read_group(
            domain + [
                ("tailor_id", "!=", False),
                ("status", "in", ["confirmed", "cutting", "sewing", "qc", "ready_delivery"]),
            ],
            ["tailor_id"],
            ["tailor_id"],
            lazy=False,
        )
        top_tailors_data = []
        for row in top_tailors:
            tailor = row.get("tailor_id")
            if tailor:
                top_tailors_data.append({
                    "label": tailor[1],
                    "value": (row.get("__count") or row.get("tailor_id_count") or 0),
                })

        # Missing docs by type
        miss_by_type = Docs.read_group(doc_domain, ["id:count"], ["document_type"], lazy=False)
        doc_type_map = dict(Docs._fields["document_type"].get_description(self.env)["selection"])

        missing_by_type = []
        for row in miss_by_type:
            t = row.get("document_type")
            missing_by_type.append({
                "label": doc_type_map.get(t, t),
                "value": (row.get("__count") or row.get("id_count") or 0),
            })

        # ✅ Top Models (by quantity) — works with your product_id + quantity
        top_models = []
        top_models_rg = TailorOrder.read_group(
            domain + [("product_id", "!=", False)],
            ["quantity:sum"],
            ["product_id"],
            orderby="quantity_sum desc",
            limit=10,
            lazy=False,
        )
        for row in top_models_rg:
            prod = row.get("product_id")
            top_models.append({
                "label": prod[1] if prod else self.env._("Unknown"),
                "value": row.get("quantity_sum") or 0.0,
            })

        # ✅ Top Fabrics (YOUR FIELD is fabric_type Many2one)
        top_fabrics = []
        top_fabrics_rg = TailorOrder.read_group(
            domain + [("fabric_type", "!=", False)],
            ["fabric_qty:sum"],
            ["fabric_type"],
            orderby="fabric_qty_sum desc",
            limit=10,
            lazy=False,
        )
        for row in top_fabrics_rg:
            f = row.get("fabric_type")
            top_fabrics.append({
                "label": f[1] if f else "Unknown",
                "value": row.get("fabric_qty_sum") or 0.0,
            })

        # ✅ FIXED: Revenue vs Fabric Cost vs Profit (by Month)
        rev_map = {r["label"]: float(r["value"] or 0.0) for r in revenue_by_month}

        cost_trend = TailorOrder.read_group(
            domain,
            ["fabric_total_cost:sum"],
            ["order_date:month"],
            lazy=False,
        )
        cost_map = {}
        for row in cost_trend:
            m_label = _safe_month_label(row.get("order_date:month"))
            cost_map[m_label] = float(row.get("fabric_total_cost_sum") or 0.0)

        months = sorted(set(list(rev_map.keys()) + list(cost_map.keys())))

        rev_cost_profit_by_month = []
        for m in months:
            r = float(rev_map.get(m, 0.0))
            c = float(cost_map.get(m, 0.0))
            rev_cost_profit_by_month.append({
                "label": m,
                "revenue": round(r, 2),
                "fabric_cost": round(c, 2),
                "profit": round(r - c, 2),
            })

        return {
            "filters": {
                "date_from": date_from or False,
                "date_to": date_to or False,
                "company_id": int(company_id) if company_id else False,

                # ✅ ADDED: return new filters (nice for UI sync / debugging)
                "tailor_id": int(tailor_id) if tailor_id else False,
                "status": status or False,
                "range": range or False,
            },
            "kpis": {
                "total_orders": total_orders,
                "active_orders": len(active),
                "delivered_orders": len(delivered),
                "cancelled_orders": len(cancelled),
                "qc_orders": len(qc),
                "ready_delivery_orders": len(ready_delivery),
                "on_time_pct": round(on_time_pct, 2),
                "avg_lead_days": round(avg_lead_days, 2),
                "total_revenue": round(total_revenue, 2),
                "total_vat": round(total_vat, 2),
                "total_balance_due": round(total_balance_due, 2),
                "missing_docs": missing_docs_count,
                "qc_pass_rate": round(qc_pass_rate, 2),
                "accessory_qty": round(accessory_qty, 2),
                "fabric_m": round(fabric_m, 2),

                # ✅ SHOWROOM KPIs
                "new_orders_today": new_orders_today,
                "pending_quotations": pending_quotations,
                "showroom_conversion_rate": round(showroom_conversion_rate, 2),

                # ✅ Profitability
                "fabric_cost_total": round(fabric_cost_total, 2),
                "gross_profit": round(gross_profit, 2),
                "profit_margin_pct": round(profit_margin_pct, 2),
                "avg_order_value": round(avg_order_value, 2),
            },
            "charts": {
                "orders_by_status": by_status,
                "orders_by_month": orders_by_month,
                "revenue_by_month": revenue_by_month,
                "top_tailors": top_tailors_data,
                "missing_docs_by_type": missing_by_type,

                # ✅ SHOWROOM chart
                "sales_performance": sales_performance,

                # ✅ NEW
                "top_models": top_models,
                "top_fabrics": top_fabrics,
                "rev_cost_profit_by_month": rev_cost_profit_by_month,
            },
        }
