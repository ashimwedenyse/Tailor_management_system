# -*- coding: utf-8 -*-
from odoo import models, fields, tools


class TailorSalesReport(models.Model):
    _name = "tailor.sales.report"
    _description = "Tailor Sales Report"
    _auto = False
    _rec_name = "order_date"

    order_id = fields.Many2one("tailor.order", string="Order", readonly=True)
    order_date = fields.Date(string="Order Date", readonly=True)
    order_week = fields.Date(string="Week", readonly=True)
    order_month = fields.Date(string="Month", readonly=True)
    order_year = fields.Integer(string="Year", readonly=True)

    partner_id = fields.Many2one("res.partner", string="Customer", readonly=True)
    product_id = fields.Many2one("product.product", string="Product", readonly=True)
    garment_template = fields.Char(string="Garment/Fabric", readonly=True)

    quantity = fields.Float(string="Quantity", readonly=True)
    orders_count = fields.Integer(string="Orders", readonly=True)

    status = fields.Selection([
        ("draft", "Draft"),
        ("measurement", "Measurement Taken"),
        ("cutting", "Cutting"),
        ("sewing", "Sewing"),
        ("ready_delivery", "Ready for Delivery"),
        ("delivered", "Delivered"),
        ("cancel", "Cancelled"),
    ], string="Stage/Status", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %(view)s AS (
                SELECT
                    row_number() OVER () AS id,
                    o.id AS order_id,
                    o.order_date AS order_date,
                    date_trunc('week', o.order_date)::date AS order_week,
                    date_trunc('month', o.order_date)::date AS order_month,
                    EXTRACT(YEAR FROM o.order_date)::int AS order_year,

                    o.partner_id AS partner_id,
                    o.product_id AS product_id,
                    o.garment_template AS garment_template,

                    COALESCE(o.quantity, 0.0) AS quantity,
                    1 AS orders_count,

                    o.status AS status
                FROM tailor_order o
                WHERE o.order_date IS NOT NULL
            )
        """ % {"view": self._table})
