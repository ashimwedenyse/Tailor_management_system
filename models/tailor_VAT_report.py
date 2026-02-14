# -*- coding: utf-8 -*-
from odoo import models, fields, tools


class TailorVATReport(models.Model):
    _name = "tailor.vat.report"
    _description = "Tailor VAT Report (Internal)"
    _auto = False
    _rec_name = "invoice_name"
    _order = "invoice_date desc, id desc"

    company_id = fields.Many2one("res.company", readonly=True)
    partner_id = fields.Many2one("res.partner", readonly=True)
    customer = fields.Char(readonly=True)

    invoice_id = fields.Many2one("account.move", readonly=True)
    invoice_name = fields.Char(readonly=True)

    invoice_date = fields.Date(readonly=True)
    invoice_date_due = fields.Date(readonly=True)

    state = fields.Selection(
        [("draft", "Draft"), ("posted", "Posted"), ("cancel", "Cancelled")],
        readonly=True,
    )

    currency_id = fields.Many2one("res.currency", readonly=True)

    amount_untaxed = fields.Monetary(currency_field="currency_id", readonly=True)
    amount_tax = fields.Monetary(currency_field="currency_id", readonly=True)
    amount_total = fields.Monetary(currency_field="currency_id", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    am.id AS id,
                    am.id AS invoice_id,
                    am.name AS invoice_name,
                    am.company_id AS company_id,
                    am.partner_id AS partner_id,
                    rp.name AS customer,
                    am.invoice_date AS invoice_date,
                    am.invoice_date_due AS invoice_date_due,
                    am.state AS state,
                    am.currency_id AS currency_id,
                    COALESCE(am.amount_untaxed, 0.0) AS amount_untaxed,
                    COALESCE(am.amount_tax, 0.0) AS amount_tax,
                    COALESCE(am.amount_total, 0.0) AS amount_total
                FROM account_move am
                LEFT JOIN res_partner rp ON rp.id = am.partner_id
                WHERE am.move_type IN ('out_invoice', 'out_refund')
                  AND am.state IN ('posted')
            )
        """)
# -*- coding: utf-8 -*-
from odoo import models, fields, tools


class TailorVATReport(models.Model):
    _name = "tailor.vat.report"
    _description = "Tailor VAT Report (Internal)"
    _auto = False
    _rec_name = "invoice_name"
    _order = "invoice_date desc, id desc"

    invoice_id = fields.Many2one("account.move", readonly=True)
    invoice_name = fields.Char(readonly=True)

    company_id = fields.Many2one("res.company", readonly=True)
    partner_id = fields.Many2one("res.partner", readonly=True)
    customer = fields.Char(readonly=True)

    invoice_date = fields.Date(readonly=True)
    invoice_date_due = fields.Date(readonly=True)

    currency_id = fields.Many2one("res.currency", readonly=True)

    amount_untaxed = fields.Monetary(currency_field="currency_id", readonly=True)
    amount_tax = fields.Monetary(currency_field="currency_id", readonly=True)
    amount_total = fields.Monetary(currency_field="currency_id", readonly=True)

    def init(self):
        # ✅ IMPORTANT: drop first to avoid "cannot drop columns from view"
        tools.drop_view_if_exists(self.env.cr, self._table)

        self.env.cr.execute(f"""
            CREATE VIEW {self._table} AS (
                SELECT
                    am.id AS id,
                    am.id AS invoice_id,
                    am.name AS invoice_name,
                    am.company_id AS company_id,
                    am.partner_id AS partner_id,
                    rp.name AS customer,
                    am.invoice_date AS invoice_date,
                    am.invoice_date_due AS invoice_date_due,
                    am.currency_id AS currency_id,
                    COALESCE(am.amount_untaxed, 0.0) AS amount_untaxed,
                    COALESCE(am.amount_tax, 0.0) AS amount_tax,
                    COALESCE(am.amount_total, 0.0) AS amount_total
                FROM account_move am
                LEFT JOIN res_partner rp ON rp.id = am.partner_id
                WHERE am.move_type IN ('out_invoice', 'out_refund')
                  AND am.state = 'posted'
            )
        """)
