# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError
from odoo.tools.translate import _
import logging

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    # ------------------------------------------------------------
    # Tailor Order link (core)
    # ------------------------------------------------------------
    tailor_order_id = fields.Many2one("tailor.order", string="Tailor Order", index=True)

    # ------------------------------------------------------------
    # Materials gate mirrors Tailor Order
    # ------------------------------------------------------------
    stock_checked = fields.Boolean(related="tailor_order_id.stock_checked", readonly=True)
    admin_materials_approved = fields.Boolean(related="tailor_order_id.admin_materials_approved", readonly=True)

    # -------------------- Tailor Order Info (SHOW INSIDE MO) --------------------
    garment_template = fields.Selection(related="tailor_order_id.garment_template", readonly=True)
    measurement_diagram = fields.Binary(related="tailor_order_id.display_diagram", readonly=True)

    # Measurements (use Tailor Order values)
    length = fields.Float(related="tailor_order_id.length", readonly=True)
    shoulder = fields.Float(related="tailor_order_id.shoulder", readonly=True)
    sleeve_length = fields.Float(related="tailor_order_id.sleeve_length", readonly=True)
    chest = fields.Float(related="tailor_order_id.chest", readonly=True)
    waist = fields.Float(related="tailor_order_id.waist", readonly=True)
    hip = fields.Float(related="tailor_order_id.hip", readonly=True)
    neck = fields.Float(related="tailor_order_id.neck", readonly=True)
    bottom_width = fields.Float(related="tailor_order_id.bottom_width", readonly=True)

    # Style options (same as Tailor Order)
    front_design = fields.Selection(related="tailor_order_id.front_design", readonly=True)
    sleeve_style = fields.Selection(related="tailor_order_id.sleeve_style", readonly=True)
    collar_style = fields.Selection(related="tailor_order_id.collar_style", readonly=True)
    cuff_style = fields.Selection(related="tailor_order_id.cuff_style", readonly=True)
    buttons_type = fields.Selection(related="tailor_order_id.buttons_type", readonly=True)
    stitching_type = fields.Selection(related="tailor_order_id.stitching_type", readonly=True)

    # Pockets
    pocket_pen_big = fields.Boolean(related="tailor_order_id.pocket_pen_big", readonly=True)
    pocket_pen_small = fields.Boolean(related="tailor_order_id.pocket_pen_small", readonly=True)
    pocket_front = fields.Boolean(related="tailor_order_id.pocket_front", readonly=True)
    pocket_key_left = fields.Boolean(related="tailor_order_id.pocket_key_left", readonly=True)
    pocket_key_right = fields.Boolean(related="tailor_order_id.pocket_key_right", readonly=True)

    # Notes / preferences (RELATED DISPLAY FIELDS)
    to_fabric_preference = fields.Char(related="tailor_order_id.fabric_preference", readonly=True)
    to_style_preference = fields.Text(related="tailor_order_id.style_preference", readonly=True)
    to_fitting_style = fields.Char(related="tailor_order_id.fitting_style", readonly=True)
    to_measurement_notes = fields.Text(related="tailor_order_id.measurement_notes", readonly=True)

    # ------------------------------------------------------------
    # KEEP your original MO custom fields (unchanged)
    # ------------------------------------------------------------
    product_typ = fields.Many2one(
        "product.product",
        string="Product",
        required=True,
        domain=[("sale_ok", "=", True)],
    )
    sale_order_id = fields.Many2one("sale.order", string="Sale Order")
    tailor_id = fields.Many2one("res.partner", string="Tailor")
    delivery_date = fields.Datetime(string="Delivery Date")

    tailor_status = fields.Selection(
        [
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
            ("cutting", "Ready for Cutting"),
            ("sewing", "Sewing"),
            ("qc", "Quality Inspection"),
            ("ready_delivery", "Ready for Delivery"),
            ("delivered", "Delivered"),
            ("cancel", "Cancelled"),
        ],
        string="Tailor Status",
        default="draft",
        tracking=True,
    )

    is_tailoring_order = fields.Boolean(string="Is Tailoring Order")
    tailor_model = fields.Char(string="Tailoring Model")
    fabric_type = fields.Char(string="Fabric Type")

    style_preference = fields.Text(string="Style Preference")
    fitting_style = fields.Char(string="Fitting Style")
    measurement_notes = fields.Text(string="Measurement Notes")
    chest_size = fields.Float(string="Chest Size")
    waist_size = fields.Float(string="Waist Size")
    hip_size = fields.Float(string="Hip Size")
    height = fields.Float(string="Height")
    fabric_preference = fields.Char(string="Fabric Preference")

    partner_id = fields.Many2one("res.partner", string="Customer")

    # -------------------- QC (from Tailor Order) --------------------
    qc_approved = fields.Boolean(related="tailor_order_id.qc_approved", readonly=True)
    qc_manager_comment = fields.Text(related="tailor_order_id.qc_manager_comment", readonly=True)

    measurements_ids = fields.Many2many("customer.measurements", string="Tailor Measurements")

    customer_measurement_history_ids = fields.One2many(
        "customer.measurements",
        compute="_compute_customer_measurement_history",
        string="Customer Measurement History",
        readonly=True,
    )

    @api.depends("partner_id")
    def _compute_customer_measurement_history(self):
        for mo in self:
            if mo.partner_id:
                mo.customer_measurement_history_ids = self.env["customer.measurements"].sudo().search(
                    [("partner_id", "=", mo.partner_id.id)],
                    order="measurement_date desc",
                )
            else:
                mo.customer_measurement_history_ids = False

    # ------------------------------------------------------------
    # Sync helpers
    # ------------------------------------------------------------
    def _sync_tailor_order_from_mo(self):
        for mo in self:
            if mo.tailor_order_id and mo.tailor_order_id.status != mo.tailor_status:
                mo.tailor_order_id.sudo().write({"status": mo.tailor_status})

    def _push_ready_delivery_to_tailor(self):
        for mo in self:
            if mo.tailor_status != "ready_delivery":
                mo.with_context(skip_tailor_push=True).write({"tailor_status": "ready_delivery"})
            if mo.tailor_order_id and mo.tailor_order_id.status != "ready_delivery":
                mo.tailor_order_id.sudo().write({"status": "ready_delivery"})

            # ✅ Create Delivery activity when MO done
            if mo.tailor_order_id:
                mo.tailor_order_id._schedule_stage_activity("ready_delivery")

    # ------------------------------------------------------------
    # ✅ QC gate (BLOCK produce all / mark done unless QC approved)
    # ------------------------------------------------------------
    def _check_tailor_qc_before_done(self):
        for mo in self:
            if mo.tailor_order_id and not mo.tailor_order_id.qc_approved:
                raise UserError(_("You cannot complete this Manufacturing Order until QC is approved by a manager."))

    # ------------------------------------------------------------
    # ONLY 3 buttons in MO
    # ------------------------------------------------------------
    def _check_materials_gate_before_production(self):
        for mo in self:
            if mo.tailor_order_id:
                if not mo.stock_checked:
                    raise UserError(_(
                        "Production cannot start yet.\n"
                        "Stock Manager must Check & Reserve Materials on the Tailor Order first."
                    ))
                if not mo.admin_materials_approved:
                    raise UserError(_(
                        "Production cannot start yet.\n"
                        "A Manager must Approve Materials on the Tailor Order first."
                    ))

    def action_mo_cutting(self):
        self._check_materials_gate_before_production()
        self.write({"tailor_status": "cutting"})

    def action_mo_sewing(self):
        self._check_materials_gate_before_production()
        self.write({"tailor_status": "sewing"})

    def action_send_to_admin(self):
        self._check_materials_gate_before_production()
        self.write({"tailor_status": "qc"})
        # ✅ Create QC activity
        for mo in self:
            if mo.tailor_order_id:
                mo.tailor_order_id._schedule_stage_activity("qc")

    # ------------------------------------------------------------
    # Auto-link Tailor Order to MO + fill customer/tailor/dates
    # ------------------------------------------------------------
    def _try_link_tailor_order(self):
        for mo in self:
            tailor = mo.tailor_order_id

            if tailor:
                if not mo.partner_id and getattr(tailor, "partner_id", False):
                    mo.partner_id = tailor.partner_id.id

                if not mo.tailor_id and getattr(tailor, "tailor_id", False):
                    try:
                        comodel = tailor._fields["tailor_id"].comodel_name
                    except Exception:
                        comodel = None

                    if comodel == "res.users":
                        mo.tailor_id = tailor.tailor_id.partner_id.id if tailor.tailor_id else False
                    else:
                        mo.tailor_id = tailor.tailor_id.id

                if not mo.delivery_date and getattr(tailor, "delivery_date", False):
                    mo.delivery_date = tailor.delivery_date

                if "is_tailoring_order" in mo._fields and not mo.is_tailoring_order:
                    mo.is_tailoring_order = True

                measures = self.env["customer.measurements"].sudo().search(
                    [("partner_id", "=", mo.partner_id.id)] if mo.partner_id else [],
                    order="measurement_date desc",
                )
                if measures:
                    mo.measurements_ids = [(6, 0, measures.ids)]
                continue

            found = False
            if mo.sale_order_id:
                found = self.env["tailor.order"].search([("sale_order_id", "=", mo.sale_order_id.id)], limit=1)

            if not found and mo.origin:
                found = self.env["tailor.order"].search([("name", "=", mo.origin)], limit=1)

            if found:
                mo.tailor_order_id = found.id

                if not mo.partner_id and getattr(found, "partner_id", False):
                    mo.partner_id = found.partner_id.id

                if not mo.tailor_id and getattr(found, "tailor_id", False):
                    try:
                        comodel = found._fields["tailor_id"].comodel_name
                    except Exception:
                        comodel = None

                    if comodel == "res.users":
                        mo.tailor_id = found.tailor_id.partner_id.id if found.tailor_id else False
                    else:
                        mo.tailor_id = found.tailor_id.id

                if not mo.delivery_date and getattr(found, "delivery_date", False):
                    mo.delivery_date = found.delivery_date

                if "is_tailoring_order" in mo._fields and not mo.is_tailoring_order:
                    mo.is_tailoring_order = True

                measures = self.env["customer.measurements"].sudo().search(
                    [("partner_id", "=", mo.partner_id.id)] if mo.partner_id else [],
                    order="measurement_date desc",
                )
                if measures:
                    mo.measurements_ids = [(6, 0, measures.ids)]

    @api.onchange("sale_order_id", "origin", "tailor_order_id")
    def _onchange_try_link_tailor_order(self):
        self._try_link_tailor_order()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._try_link_tailor_order()
        return records

    # ------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------
    def write(self, vals):
        # ✅ block state done
        if vals.get("state") == "done":
            self._check_tailor_qc_before_done()

        # ✅ also block any tailoring progress if materials were not checked + approved
        if vals.get("tailor_status") in ("cutting", "sewing", "qc"):
            self._check_materials_gate_before_production()

        res = super().write(vals)

        if "sale_order_id" in vals or "origin" in vals or "tailor_order_id" in vals:
            self._try_link_tailor_order()

        if "tailor_status" in vals and not self.env.context.get("skip_tailor_push"):
            self._sync_tailor_order_from_mo()

        if vals.get("state") == "done":
            self._push_ready_delivery_to_tailor()

        return res

    def button_mark_done(self):
        self._check_tailor_qc_before_done()
        res = super().button_mark_done()

        for mo in self:
            if mo.state == "done":
                mo._push_ready_delivery_to_tailor()
        return res

    def _post_inventory(self, *args, **kwargs):
        # ✅ strongest protection (covers Produce All paths)
        self._check_tailor_qc_before_done()
        return super()._post_inventory(*args, **kwargs)


class ResPartner(models.Model):
    _inherit = "res.partner"

    measurements_ids = fields.One2many("customer.measurements", "partner_id", string="Tailor Measurements")
