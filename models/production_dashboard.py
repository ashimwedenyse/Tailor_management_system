# -*- coding: utf-8 -*-
import logging
from datetime import datetime, date, timedelta

from odoo import models, api, fields

_logger = logging.getLogger(__name__)


class TailorProductionDashboard(models.AbstractModel):
    _name = "tailor.production.dashboard"
    _description = "Tailor Production Dashboard (Manufacturing Efficiency)"

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------
    def _parse_filters(self, filters):
        filters = filters or {}
        date_from = filters.get("date_from") or False
        date_to = filters.get("date_to") or False
        company_id = filters.get("company_id") or False

        # optional: limit stock alerts to fabrics
        only_fabrics = bool(filters.get("only_fabrics")) if isinstance(filters, dict) else False

        try:
            company_id = int(company_id) if company_id else False
        except Exception:
            company_id = False

        df = fields.Date.from_string(date_from) if date_from else False
        dt = fields.Date.from_string(date_to) if date_to else False
        return df, dt, company_id, only_fabrics

    def _pick_first_existing_field(self, model, candidates, default=None):
        flds = model._fields
        for name in candidates:
            if name in flds:
                return name
        return default

    def _domain_from_dates(self, df, dt, field_name):
        domain = []
        if not field_name:
            return domain
        if df:
            start_dt = fields.Datetime.to_datetime(df)
            domain.append((field_name, ">=", start_dt))
        if dt:
            end_dt = fields.Datetime.to_datetime(dt) + timedelta(days=1) - timedelta(seconds=1)
            domain.append((field_name, "<=", end_dt))
        return domain

    def _to_dt(self, v):
        if not v:
            return False
        if isinstance(v, datetime):
            return v
        if isinstance(v, date):
            return datetime(v.year, v.month, v.day, 0, 0, 0)
        # strings
        try:
            d = fields.Date.from_string(v)
            if d:
                return datetime(d.year, d.month, d.day, 0, 0, 0)
        except Exception:
            pass
        try:
            return fields.Datetime.from_string(v)
        except Exception:
            return False

    def _date_only(self, v):
        if not v:
            return False
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, date):
            return v
        return False

    def _safe_month_label(self, val):
        if not val:
            return "Unknown"
        if isinstance(val, datetime):
            return val.strftime("%B %Y")
        if isinstance(val, date):
            return val.strftime("%B %Y")
        if isinstance(val, str):
            s = val.strip()
            try:
                d = fields.Date.from_string(s)
                if d:
                    return d.strftime("%B %Y")
            except Exception:
                pass
            return s
        return str(val)

    def _rg_count(self, row):
        return (
            row.get("__count")
            or row.get("id_count")
            or row.get("order_date_count")
            or row.get("date_order_count")
            or row.get("create_date_count")
            or row.get("status_changed_on_count")
            or row.get("write_date_count")
            or 0
        )

    # ✅ NEW: Arabic status labels for ACTIVE ORDERS / KANBAN / TABLES
    def _is_ar(self):
        lang = (self.env.context.get("lang") or self.env.user.lang or "")
        return lang.startswith("ar")

    def _status_label(self, key, fallback_labels=None):
        """
        Return a display label for a status key.
        - If Arabic lang => use Arabic mapping (stable)
        - Else => use selection labels (fallback_labels) or key
        """
        # Core tailor.order workflow keys
        ar = {
            "draft": "مسودة",
            "confirmed": "مؤكد",
            "cutting": "جاهز للقص",
            "sewing": "الخياطة",
            "qc": "فحص الجودة",
            "ready_delivery": "جاهز للتسليم",
            "delivered": "تم التسليم",
            "cancel": "ملغي",
        }
        if self._is_ar():
            return ar.get(key, key)

        # non-ar: prefer selection label if provided
        if fallback_labels and key in fallback_labels:
            return fallback_labels.get(key)
        return key

    # ------------------------------------------------------------
    # Main RPC
    # ------------------------------------------------------------
    @api.model
    def get_kpis(self, filters=None):
        df, dt, company_id, only_fabrics = self._parse_filters(filters)

        TailorOrder = self.env["tailor.order"].sudo()

        order_date_field = self._pick_first_existing_field(
            TailorOrder, ["order_date", "date_order", "create_date"], default="create_date"
        )
        delivered_date_field = self._pick_first_existing_field(
            TailorOrder, ["status_changed_on", "write_date"], default="write_date"
        )

        domain = []
        if company_id and "company_id" in TailorOrder._fields:
            domain.append(("company_id", "=", company_id))
        domain += self._domain_from_dates(df, dt, order_date_field)

        orders = TailorOrder.search(domain)

        _logger.info(
            "[ProductionDashboard] date_field=%s delivered_field=%s df=%s dt=%s company_id=%s -> orders=%s",
            order_date_field, delivered_date_field, df, dt, company_id, len(orders)
        )

        status_field = "status" if "status" in TailorOrder._fields else None

        def _st(o):
            return getattr(o, status_field) if status_field else False

        cutting = orders.filtered(lambda o: _st(o) == "cutting")
        sewing = orders.filtered(lambda o: _st(o) == "sewing")
        qc = orders.filtered(lambda o: _st(o) == "qc")
        ready_delivery = orders.filtered(lambda o: _st(o) == "ready_delivery")
        delivered = orders.filtered(lambda o: _st(o) == "delivered")

        wip = orders.filtered(lambda o: _st(o) in ("confirmed", "cutting", "sewing", "qc", "ready_delivery"))

        # status labels safe
        status_labels = {}
        try:
            if status_field:
                status_labels = dict(TailorOrder._fields[status_field].selection)
        except Exception:
            status_labels = {}

        # Bottleneck stage (✅ improved labels to be Arabic-safe)
        stage_counts = {
            "cutting": len(cutting),
            "sewing": len(sewing),
            "qc": len(qc),
            "ready_delivery": len(ready_delivery),
        }
        bottleneck_key = max(stage_counts, key=stage_counts.get) if stage_counts else "N/A"
        bottleneck_count = stage_counts.get(bottleneck_key, 0)
        bottleneck_stage = (
            self._status_label(bottleneck_key, fallback_labels=status_labels)
            if bottleneck_key != "N/A"
            else "N/A"
        )

        # =========================================================
        # ✅✅ FIXED EFFICIENCY (BEST SOURCE = mrp.production)
        # =========================================================
        avg_cycle_days = 0.0
        avg_qc_days = 0.0

        # 1) Try compute Avg Cycle from linked Manufacturing Orders (MOST ACCURATE)
        try:
            MO = self.env["mrp.production"].sudo()

            # detect the link field on tailor.order that points to a manufacturing order
            mo_link_field = self._pick_first_existing_field(
                TailorOrder,
                ["mrp_id", "production_id", "mrp_production_id"],
                default=None,
            )

            mos = MO.browse()
            if mo_link_field:
                mo_ids = orders.mapped(mo_link_field).ids
                if mo_ids:
                    mos = MO.browse(mo_ids).exists()

            # Compute cycle from MO dates (done or not)
            cycle_vals = []
            if mos:
                for mo in mos:
                    # pick best start/end
                    start = self._to_dt(getattr(mo, "date_start", False)) \
                        or self._to_dt(getattr(mo, "date_planned_start", False)) \
                        or self._to_dt(getattr(mo, "create_date", False))

                    end = self._to_dt(getattr(mo, "date_finished", False)) \
                        or self._to_dt(getattr(mo, "write_date", False))

                    if start and end and end >= start:
                        cycle_vals.append((end - start).total_seconds() / 86400.0)

                if cycle_vals:
                    avg_cycle_days = sum(cycle_vals) / len(cycle_vals)

        except Exception as e:
            _logger.warning("Efficiency (MO cycle) skipped: %s", e)

        # 2) Fallback if MO-based cycle failed
        if not avg_cycle_days:
            cycle_days = []
            for o in delivered:
                od = self._to_dt(getattr(o, order_date_field, False))
                dd = self._to_dt(getattr(o, delivered_date_field, False))
                if od and dd and dd >= od:
                    cycle_days.append((dd - od).total_seconds() / 86400.0)
            avg_cycle_days = (sum(cycle_days) / len(cycle_days)) if cycle_days else 0.0

        # 3) QC time: keep your existing logic, but fix types (Date/Datetime safe)
        qc_vals = []
        for o in orders:
            qc_on = self._to_dt(getattr(o, "qc_approved_on", False))
            od = self._to_dt(getattr(o, order_date_field, False))
            if qc_on and od and qc_on >= od:
                qc_vals.append((qc_on - od).total_seconds() / 86400.0)
        avg_qc_days = (sum(qc_vals) / len(qc_vals)) if qc_vals else 0.0

        # QC pass rate
        qc_pass = delivered.filtered(lambda o: bool(getattr(o, "qc_approved", False)))
        qc_pass_pct = (len(qc_pass) / len(delivered) * 100.0) if delivered else 0.0

        # -------------------------
        # Delayed Orders (deadline < today) with fallback to delivery_date
        # -------------------------
        today = fields.Date.today()

        def _get_deadline(o):
            return getattr(o, "date_deadline", False)

        def _get_delivery(o):
            return getattr(o, "delivery_date", False)

        delayed_orders = orders.filtered(
            lambda o: _st(o) not in ("delivered", "cancel")
            and (
                (_get_deadline(o) and self._date_only(_get_deadline(o)) and self._date_only(_get_deadline(o)) < today)
                or (not _get_deadline(o) and _get_delivery(o) and self._date_only(_get_delivery(o)) and self._date_only(_get_delivery(o)) < today)
            )
        )

        delayed_preview = []

        def _sort_delayed(x):
            return self._date_only(_get_deadline(x)) or self._date_only(_get_delivery(x)) or today

        for o in delayed_orders.sorted(_sort_delayed)[:10]:
            dd = _get_deadline(o)
            dv = _get_delivery(o)
            delayed_preview.append({
                "id": o.id,
                "name": o.name,
                "customer": o.partner_id.name if o.partner_id else "",
                # ✅ Arabic-safe status
                "status": self._status_label(_st(o), fallback_labels=status_labels),
                "date_deadline": fields.Date.to_string(self._date_only(dd)) if dd else "",
                "delivery_date": fields.Date.to_string(self._date_only(dv)) if dv else "",
                "is_delayed": True,
            })

        # -------------------------
        # ✅✅ LATE ORDERS (UPDATED):
        # Late Orders = deadline is TODAY (or fallback delivery_date TODAY)
        # status must NOT be delivered/cancel
        # -------------------------
        def _is_due_today(o):
            if _st(o) in ("delivered", "cancel"):
                return False

            dd = self._date_only(_get_deadline(o))
            if dd:
                return dd == today

            # fallback if no deadline: use delivery_date == today
            dv = self._date_only(_get_delivery(o))
            return bool(dv and dv == today)

        late_orders = orders.filtered(_is_due_today)

        # Fabric + Accessories planned (WIP)
        late_fabric_m = 0.0
        if wip and "fabric_qty" in TailorOrder._fields:
            late_fabric_m = sum(wip.mapped("fabric_qty")) or 0.0

        late_accessories_qty = 0.0
        if "accessory_line_ids" in TailorOrder._fields:
            for o in wip:
                for line in o.accessory_line_ids:
                    late_accessories_qty += float(getattr(line, "quantity", 0.0) or 0.0)

        # -------------------------
        # Kanban Board (✅ improved titles + card status consistency)
        # -------------------------
        KANBAN_STAGES = ["confirmed", "cutting", "sewing", "qc", "ready_delivery"]
        kanban_columns = []

        for st in KANBAN_STAGES:
            st_orders = orders.filtered(lambda o, _stg=st: _st(o) == _stg)
            cards = []
            for o in st_orders[:50]:
                dd = _get_deadline(o)
                ddel = getattr(o, "delivery_date", False)
                delivery_str = ""
                if ddel:
                    delivery_str = fields.Date.to_string(self._date_only(ddel)) if self._date_only(ddel) else str(ddel)

                cards.append({
                    "id": o.id,
                    "name": o.name,
                    "customer": o.partner_id.name if o.partner_id else "",
                    "tailor": o.tailor_id.name if getattr(o, "tailor_id", False) else "",
                    "delivery_date": delivery_str,
                    "date_deadline": fields.Date.to_string(self._date_only(dd)) if dd else "",
                    "is_delayed": bool((self._date_only(dd) and self._date_only(dd) < today) or (not dd and self._date_only(ddel) and self._date_only(ddel) < today)),
                    # ✅ (optional) include status label per card (helps UI if needed)
                    "status": self._status_label(_st(o), fallback_labels=status_labels),
                    "status_key": _st(o),
                })
            kanban_columns.append({
                "key": st,
                # ✅ Arabic-safe column title
                "title": self._status_label(st, fallback_labels=status_labels),
                "count": len(st_orders),
                "cards": cards,
            })

        # -------------------------
        # ✅✅✅ ONLY FIXED HERE: Tailor Productivity (FINISHED / COMPLETED MOs)
        # -------------------------
        tailor_productivity = []
        try:
            MO = self.env["mrp.production"].sudo()

            mo_domain = [("state", "=", "done")]
            if company_id and "company_id" in MO._fields:
                mo_domain.append(("company_id", "=", company_id))

            mo_date_field = self._pick_first_existing_field(
                MO,
                ["date_finished", "date_end", "write_date", "create_date"],
                default="write_date",
            )
            mo_domain += self._domain_from_dates(df, dt, mo_date_field)

            # ✅ pick the best available “tailor” field on mrp.production
            tailor_field = self._pick_first_existing_field(
                MO,
                [
                    "x_assigned_tailor",
                    "x_tailor_id",
                    "employee_id",
                    "user_id",
                    "responsible_id",
                ],
                default=None,
            )

            if tailor_field:
                rg = MO.read_group(
                    mo_domain + [(tailor_field, "!=", False)],
                    [tailor_field],
                    [tailor_field],
                    lazy=False,
                )
                for r in rg:
                    t = r.get(tailor_field)
                    if t:
                        label = t[1] if isinstance(t, (list, tuple)) and len(t) > 1 else str(t)
                        tailor_productivity.append({
                            "label": label,
                            "value": r.get("__count") or r.get(f"{tailor_field}_count") or 0,
                        })
            else:
                if "workorder_ids" in MO._fields:
                    mos = MO.search(mo_domain)
                    counts = {}
                    for mo in mos:
                        for wo in mo.workorder_ids:
                            emp = False
                            if "employee_id" in wo._fields:
                                emp = wo.employee_id
                            elif "x_assigned_tailor" in wo._fields:
                                emp = wo.x_assigned_tailor
                            if emp:
                                counts[emp.display_name] = counts.get(emp.display_name, 0) + 1
                    tailor_productivity = [{"label": k, "value": v} for k, v in sorted(counts.items(), key=lambda x: x[1], reverse=True)]

        except Exception as e:
            _logger.warning("Tailor productivity (MOs) skipped: %s", e)

        # -------------------------
        # Stock Alerts (NEGATIVE AVAILABLE = quantity - reserved)
        # -------------------------
        stock_alerts = []
        try:
            Quant = self.env["stock.quant"].sudo()

            q_domain = [("location_id.usage", "=", "internal")]
            if company_id and "company_id" in Quant._fields:
                q_domain.append(("company_id", "=", company_id))

            if only_fabrics:
                q_domain.append(("product_id.categ_id.name", "ilike", "Fabric"))

            quants = Quant.search(q_domain)

            grouped = {}
            for q in quants:
                qty = float(q.quantity or 0.0)
                res = float(getattr(q, "reserved_quantity", 0.0) or 0.0)
                available = qty - res
                if available < 0:
                    key = (q.product_id.id, q.location_id.id)
                    grouped.setdefault(key, {
                        "product": q.product_id.display_name,
                        "location": q.location_id.display_name,
                        "on_hand": 0.0,
                        "min_qty": 0.0,
                        "to_order": 0.0,
                    })
                    grouped[key]["on_hand"] += available

            stock_alerts = sorted(grouped.values(), key=lambda x: x["on_hand"])
            for row in stock_alerts:
                row["to_order"] = abs(float(row["on_hand"]))

        except Exception as e:
            _logger.warning("Stock alerts (negative available) skipped: %s", e)

        # -------------------------
        # Charts
        # -------------------------
        wip_trend = TailorOrder.read_group(
            domain + [(status_field, "in", ["confirmed", "cutting", "sewing", "qc", "ready_delivery"])],
            ["id:count"],
            [f"{order_date_field}:month"],
            lazy=False,
        )
        wip_by_month = [
            {"label": self._safe_month_label(r.get(f"{order_date_field}:month")), "value": self._rg_count(r)}
            for r in wip_trend
        ]

        throughput_trend = TailorOrder.read_group(
            domain + [(status_field, "=", "delivered")],
            ["id:count"],
            [f"{delivered_date_field}:month"],
            lazy=False,
        )
        throughput_by_month = [
            {"label": self._safe_month_label(r.get(f"{delivered_date_field}:month")), "value": self._rg_count(r)}
            for r in throughput_trend
        ]

        top_tailors_wip = []
        if "tailor_id" in TailorOrder._fields:
            top_tailors_wip_rg = TailorOrder.read_group(
                domain + [
                    ("tailor_id", "!=", False),
                    (status_field, "in", ["confirmed", "cutting", "sewing", "qc", "ready_delivery"]),
                ],
                ["tailor_id"],
                ["tailor_id"],
                lazy=False,
            )
            for r in top_tailors_wip_rg:
                t = r.get("tailor_id")
                if t:
                    top_tailors_wip.append({"label": t[1], "value": r.get("__count") or r.get("tailor_id_count") or 0})

        top_tailors_delivered = []
        if "tailor_id" in TailorOrder._fields:
            top_tailors_del_rg = TailorOrder.read_group(
                domain + [("tailor_id", "!=", False), (status_field, "=", "delivered")],
                ["tailor_id"],
                ["tailor_id"],
                lazy=False,
            )
            for r in top_tailors_del_rg:
                t = r.get("tailor_id")
                if t:
                    top_tailors_delivered.append({"label": t[1], "value": r.get("__count") or r.get("tailor_id_count") or 0})

        # -------------------------
        # Late orders table preview (UPDATED to show deadline/delivery)
        # -------------------------
        late_preview = []

        def _late_sort(o):
            # show deadline first; fallback to delivery; else today
            return self._date_only(_get_deadline(o)) or self._date_only(_get_delivery(o)) or today

        for o in late_orders.sorted(_late_sort)[:10]:
            dd = _get_deadline(o)
            dv = _get_delivery(o)

            late_preview.append({
                "id": o.id,
                "name": o.name,
                "customer": o.partner_id.name if o.partner_id else "",
                # ✅ Arabic-safe status
                "status": self._status_label(_st(o), fallback_labels=status_labels),
                "status_key": _st(o),
                "date_deadline": fields.Date.to_string(self._date_only(dd)) if dd else "",
                "delivery_date": fields.Date.to_string(self._date_only(dv)) if dv else "",
            })

        return {
            "filters": {
                "date_from": fields.Date.to_string(df) if df else False,
                "date_to": fields.Date.to_string(dt) if dt else False,
                "company_id": company_id or False,
            },
            "kpis": {
                "wip_orders": len(wip),
                "cutting_orders": len(cutting),
                "sewing_orders": len(sewing),
                "qc_orders": len(qc),

                "ready_delivery": len(ready_delivery),
                "delivered": len(delivered),

                # ✅ Arabic-safe bottleneck label
                "bottleneck_stage": bottleneck_stage,
                "bottleneck_count": bottleneck_count,

                "avg_cycle_days": round(avg_cycle_days, 2),
                "avg_qc_days": round(avg_qc_days, 2),

                "qc_pass_pct": round(qc_pass_pct, 2),

                "late_orders": len(late_orders),
                "late_fabric_m": round(late_fabric_m, 2),
                "late_accessories_qty": round(late_accessories_qty, 2),

                "delayed_orders": len(delayed_orders),
                "stock_alerts": len(stock_alerts),
            },
            "charts": {
                "wip_by_month": wip_by_month,
                "throughput_by_month": throughput_by_month,
                "top_tailors_wip": top_tailors_wip,
                "top_tailors_delivered": top_tailors_delivered,
                "tailor_productivity": tailor_productivity,
            },
            "tables": {
                "late_orders": late_preview,
                "delayed_orders": delayed_preview,
                "kanban": kanban_columns,
                "stock_alerts": stock_alerts[:20],
            },
        }
