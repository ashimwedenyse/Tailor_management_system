# -*- coding: utf-8 -*-
from odoo import models, fields, tools


class TailorAgingReceivableReport(models.Model):
    _name = "tailor.aging.receivable.report"
    _description = "Tailor Aging Receivables (Internal)"
    _auto = False
    _rec_name = "invoice_name"
    _order = "days_overdue desc, invoice_date desc, id desc"

    invoice_id = fields.Many2one("account.move", readonly=True)
    invoice_name = fields.Char(readonly=True)

    company_id = fields.Many2one("res.company", readonly=True)
    partner_id = fields.Many2one("res.partner", readonly=True)
    customer = fields.Char(readonly=True)

    invoice_date = fields.Date(readonly=True)
    invoice_date_due = fields.Date(readonly=True)

    currency_id = fields.Many2one("res.currency", readonly=True)

    amount_total = fields.Monetary(currency_field="currency_id", readonly=True)
    amount_residual = fields.Monetary(currency_field="currency_id", readonly=True)

    days_overdue = fields.Integer(readonly=True)
    bucket = fields.Selection(
        [
            ("not_due", "Not Due"),
            ("b0_30", "0-30"),
            ("b31_60", "31-60"),
            ("b61_90", "61-90"),
            ("b90p", "90+"),
        ],
        readonly=True,
    )

    # Pivot measures
    not_due = fields.Monetary(currency_field="currency_id", readonly=True)
    b0_30 = fields.Monetary(currency_field="currency_id", readonly=True)
    b31_60 = fields.Monetary(currency_field="currency_id", readonly=True)
    b61_90 = fields.Monetary(currency_field="currency_id", readonly=True)
    b90p = fields.Monetary(currency_field="currency_id", readonly=True)

    def init(self):
        # ✅ IMPORTANT: drop first to avoid "cannot drop columns from view"
        tools.drop_view_if_exists(self.env.cr, self._table)

        self.env.cr.execute(f"""
            CREATE VIEW {self._table} AS (
                WITH inv AS (
                    SELECT
                        am.id,
                        am.name AS invoice_name,
                        am.company_id,
                        am.partner_id,
                        rp.name AS customer,
                        am.invoice_date,
                        am.invoice_date_due,
                        am.currency_id,
                        COALESCE(am.amount_total, 0.0) AS amount_total,
                        COALESCE(am.amount_residual, 0.0) AS amount_residual,
                        CASE
                            WHEN am.invoice_date_due IS NULL THEN 0
                            ELSE GREATEST((CURRENT_DATE - am.invoice_date_due), 0)
                        END AS days_overdue_calc,
                        CASE
                            WHEN am.invoice_date_due IS NULL THEN 'not_due'
                            WHEN am.invoice_date_due > CURRENT_DATE THEN 'not_due'
                            WHEN (CURRENT_DATE - am.invoice_date_due) BETWEEN 0 AND 30 THEN 'b0_30'
                            WHEN (CURRENT_DATE - am.invoice_date_due) BETWEEN 31 AND 60 THEN 'b31_60'
                            WHEN (CURRENT_DATE - am.invoice_date_due) BETWEEN 61 AND 90 THEN 'b61_90'
                            ELSE 'b90p'
                        END AS bucket_calc
                    FROM account_move am
                    LEFT JOIN res_partner rp ON rp.id = am.partner_id
                    WHERE am.move_type IN ('out_invoice', 'out_refund')
                      AND am.state = 'posted'
                      AND COALESCE(am.amount_residual, 0.0) > 0
                )
                SELECT
                    id AS id,
                    id AS invoice_id,
                    invoice_name,
                    company_id,
                    partner_id,
                    customer,
                    invoice_date,
                    invoice_date_due,
                    currency_id,
                    amount_total,
                    amount_residual,
                    days_overdue_calc AS days_overdue,
                    bucket_calc AS bucket,

                    CASE WHEN bucket_calc = 'not_due' THEN amount_residual ELSE 0.0 END AS not_due,
                    CASE WHEN bucket_calc = 'b0_30'  THEN amount_residual ELSE 0.0 END AS b0_30,
                    CASE WHEN bucket_calc = 'b31_60' THEN amount_residual ELSE 0.0 END AS b31_60,
                    CASE WHEN bucket_calc = 'b61_90' THEN amount_residual ELSE 0.0 END AS b61_90,
                    CASE WHEN bucket_calc = 'b90p'   THEN amount_residual ELSE 0.0 END AS b90p
                FROM inv
            )
        """)
