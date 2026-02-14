from odoo import models, fields, tools


class TailorCogsReport(models.Model):
    _name = "tailor.cogs.report"
    _description = "Tailor COGS Report"
    _auto = False
    _rec_name = "order_name"

    order_id = fields.Many2one("tailor.order", readonly=True)
    order_name = fields.Char(string="Order", readonly=True)

    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        readonly=True,
    )

    order_date = fields.Datetime(readonly=True)
    status = fields.Selection([
        ("draft", "Draft"),
        ("confirmed", "Confirmed"),
        ("cutting", "Cutting"),
        ("sewing", "Sewing"),
        ("qc", "QC"),
        ("ready_delivery", "Ready for Delivery"),
        ("delivered", "Delivered"),
        ("cancel", "Cancelled"),
    ], readonly=True)

    sale_amount = fields.Monetary(readonly=True)
    fabric_cost = fields.Monetary(readonly=True)
    overhead_cost = fields.Monetary(readonly=True)
    total_cogs = fields.Monetary(readonly=True)
    gross_profit = fields.Monetary(readonly=True)

    company_id = fields.Many2one("res.company", readonly=True)
    currency_id = fields.Many2one(
        related="company_id.currency_id",
        readonly=True,
    )

    def init(self):
        self.env.cr.execute("DROP VIEW IF EXISTS tailor_cogs_report CASCADE")
        self.env.cr.execute("""
            CREATE VIEW tailor_cogs_report AS (
                SELECT
                    o.id AS id,
                    o.id AS order_id,
                    o.name AS order_name,
                    o.partner_id AS partner_id,
                    o.order_date,
                    o.status,
                    o.sale_amount,
                    o.fabric_cost,
                    o.overhead_cost,
                    (COALESCE(o.fabric_cost,0) + COALESCE(o.overhead_cost,0)) AS total_cogs,
                    (o.sale_amount - (COALESCE(o.fabric_cost,0) + COALESCE(o.overhead_cost,0))) AS gross_profit,
                    o.company_id
                FROM tailor_order o
                WHERE o.status IS NOT NULL
            )
        """)
