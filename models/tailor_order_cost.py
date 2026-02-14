# -*- coding: utf-8 -*-
from odoo import models, fields, api


class TailorOrder(models.Model):
    _inherit = "tailor.order"

    # Cost per meter (manual input)
    fabric_unit_cost = fields.Float(
        string="Fabric Cost per Meter",
        digits="Product Price",
        default=0.0,
        help="Cost price of fabric per meter for this order.",
    )

    # Total cost (computed)
    fabric_total_cost = fields.Float(
        string="Total Fabric Cost",
        digits="Product Price",
        compute="_compute_fabric_total_cost",
        store=True,
        readonly=True,
        help="Computed as Fabric Quantity (m) × Fabric Cost per Meter.",
    )

    @api.depends("fabric_qty", "fabric_unit_cost")
    def _compute_fabric_total_cost(self):
        for rec in self:
            qty = float(rec.fabric_qty or 0.0)
            unit = float(rec.fabric_unit_cost or 0.0)
            rec.fabric_total_cost = qty * unit
