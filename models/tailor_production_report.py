# -*- coding: utf-8 -*-
from odoo import models, fields, tools


class TailorProductionReport(models.Model):
    _name = "tailor.production.report"
    _description = "Tailor Production Report"
    _auto = False

    order_id = fields.Many2one("tailor.order", readonly=True)
    order_date = fields.Date(readonly=True)
    delivery_date = fields.Date(readonly=True)
    status = fields.Selection([
        ("draft", "Draft"),
        ("sewing", "Sewing"),
        ("ready_delivery", "Ready for Delivery"),
        ("delivered", "Delivered"),
        ("cancel", "Cancelled"),
    ], readonly=True)

    tailor_id = fields.Many2one("res.users", readonly=True)
    product_id = fields.Many2one("product.product", readonly=True)

    # ✅ MUST BE NUMERIC
    quantity = fields.Float(readonly=True, group_operator="sum")
    orders_count = fields.Integer(readonly=True, group_operator="sum")
    duration_days = fields.Float(readonly=True, group_operator="avg")

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    o.id AS id,
                    o.id AS order_id,
                    o.order_date::date AS order_date,
                    o.delivery_date::date AS delivery_date,
                    o.status AS status,
                    o.tailor_id AS tailor_id,
                    o.product_id AS product_id,

                    COALESCE(o.quantity, 0)::float8 AS quantity,
                    1::int AS orders_count,

                    -- duration in days (numeric)
                    CASE
                        WHEN o.order_date IS NOT NULL AND o.delivery_date IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (o.delivery_date::timestamp - o.order_date::timestamp)) / 86400.0
                        ELSE 0.0
                    END::float8 AS duration_days

                FROM tailor_order o
            )
        """)