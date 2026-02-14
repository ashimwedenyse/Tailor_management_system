# -*- coding: utf-8 -*-
from odoo import api, fields, models


class TailorOrderSmartButtons(models.Model):
    _inherit = "tailor.order"

    document_count = fields.Integer(string="Documents", compute="_compute_counts")
    mo_count = fields.Integer(string="Manufacturing Orders", compute="_compute_counts")
    accessory_count = fields.Integer(string="Accessories", compute="_compute_counts")

    @api.depends("document_ids", "mrp_ids", "accessory_line_ids")
    def _compute_counts(self):
        for rec in self:
            rec.document_count = len(rec.document_ids)
            rec.mo_count = len(rec.mrp_ids)
            rec.accessory_count = len(rec.accessory_line_ids)

    def action_view_documents(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Documents",
            "res_model": self.document_ids._name,
            "view_mode": "list,form",
            "domain": [("id", "in", self.document_ids.ids)],
            "context": {"default_order_id": self.id},
        }

    def action_view_mos(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Manufacturing Orders",
            "res_model": self.mrp_ids._name,  # usually mrp.production
            "view_mode": "list,form",
            "domain": [("id", "in", self.mrp_ids.ids)],
            "context": {"default_origin": self.name},
        }

    def action_view_accessories(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Accessories / Extras",
            "res_model": self.accessory_line_ids._name,
            "view_mode": "list,form",
            "domain": [("id", "in", self.accessory_line_ids.ids)],
            "context": {"default_order_id": self.id},
        }
