# -*- coding: utf-8 -*-
import base64
import logging
import mimetypes

from odoo import models, fields, api
from odoo.exceptions import UserError
from odoo.tools.translate import _
from odoo.tools.misc import file_open  # ✅ REQUIRED
from odoo.tools import float_compare  # ✅ ADDED (safe numeric compare with rounding)
from datetime import timedelta

_logger = logging.getLogger(__name__)

# ------------------------------------------------------------
# Static image loader (Odoo 17 / 18 / 19 safe)
# ------------------------------------------------------------
try:
    from odoo.modules.module import get_module_resource
except Exception:
    get_module_resource = None

try:
    from odoo.modules.module import get_resource_path
except Exception:
    get_resource_path = None


def _read_static_image(module_name, filename):
    """
    Load image from:
    <module>/static/src/img/<filename>

    Returns base64 bytes for Binary fields.
    """
    rel_path = f"{module_name}/static/src/img/{filename}"

    # ✅ Best / most reliable (works in all Odoo deployments)
    try:
        with file_open(rel_path, "rb") as f:
            data = f.read()
            _logger.info("✅ Loaded diagram using file_open: %s (%s bytes)", rel_path, len(data))
            return base64.b64encode(data)
    except Exception as e:
        _logger.warning("❌ file_open failed for %s: %s", rel_path, e)

    # Fallbacks (keep your old logic)
    path = None

    if get_module_resource:
        path = get_module_resource(module_name, "static", "src", "img", filename)

    if not path and get_resource_path:
        try:
            path = get_resource_path(module_name, "static/src/img", filename)
        except Exception:
            path = get_resource_path(module_name, "static", "src", "img", filename)

    _logger.warning("Fallback resolved path=%s for %s", path, rel_path)

    if not path:
        _logger.warning("Image not found: %s (module=%s)", filename, module_name)
        return False

    try:
        with open(path, "rb") as f:
            data = f.read()
            _logger.info("✅ Loaded diagram using open(): %s (%s bytes)", path, len(data))
            return base64.b64encode(data)
    except Exception:
        _logger.exception("Failed to load image: %s", filename)
        return False


# ------------------------------------------------------------
# Default diagrams (module-level)
# ------------------------------------------------------------
def _default_arabic_diagram(self):
    return _read_static_image("tailor_management", "arabic_kandura.png")


def _default_kuwaiti_diagram(self):
    return _read_static_image("tailor_management", "kuwaiti_kandura.png")


# -------------------- Tailor Order Model --------------------
class TailorOrder(models.Model):
    _name = "tailor.order"
    _description = "Tailor Order"
    _inherit = ["mail.thread", "mail.activity.mixin", "portal.mixin"]

    # -------------------- Customer & Order Info --------------------
    name = fields.Char(string="Order Reference", required=False, copy=False, readonly=True)
    partner_id = fields.Many2one("res.partner", string="Customer", required=True)

    # -------------------- Accessories / Extras --------------------
    accessory_line_ids = fields.One2many(
        "tailor.accessory.line",
        "tailor_order_id",
        string="Accessories / Extras",
        copy=True,
    )

    accessories_notes = fields.Text(string="Accessories Notes / Extra Requirements")

    accessories_count = fields.Integer(string="Accessories Count", compute="_compute_counts", store=False)
    accessories_pushed_to_mo = fields.Boolean(default=False)

    # ✅ Fabric costing (needed for profitability dashboard)
    fabric_unit_cost = fields.Float(
        string="Fabric Cost per Meter",
        digits="Product Price",
        default=0.0,
    )

    fabric_total_cost = fields.Float(
        string="Total Fabric Cost",
        digits="Product Price",
        compute="_compute_fabric_total_cost",
        store=True,
        readonly=True,
    )

    @api.depends("fabric_qty", "fabric_unit_cost")
    def _compute_fabric_total_cost(self):
        for rec in self:
            rec.fabric_total_cost = float(rec.fabric_qty or 0.0) * float(rec.fabric_unit_cost or 0.0)

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        required=True,
    )

    customer_name = fields.Char(
        string="Customer Name",
        related="partner_id.name",
        store=True,
        readonly=True,
    )

    style_type = fields.Selection(
        [
            ("plain", "Plain"),
            ("omani", "Omani"),
        ],
        string="Style",
        default="plain",
    )

    arabic_diagram = fields.Binary(string="Arabic Kandura Diagram", attachment=True)
    kuwaiti_diagram = fields.Binary(string="Kuwaiti Kandura Diagram", attachment=True)
    display_diagram = fields.Binary(string="Measurement Diagram", compute="_compute_display_diagram")

    customer_approved = fields.Boolean(string="Customer Approved", default=False)

    # ------------------------------------------------------------
    # Materials gate (real manufacturing control)
    # ------------------------------------------------------------
    stock_checked = fields.Boolean(string="Stock Checked & Reserved", default=False, tracking=True)
    stock_checked_by = fields.Many2one("res.users", string="Stock Checked By", readonly=True)
    stock_checked_on = fields.Datetime(string="Stock Checked On", readonly=True)

    admin_materials_approved = fields.Boolean(string="Admin Approved Materials", default=False, tracking=True)
    admin_materials_approved_by = fields.Many2one("res.users", string="Admin Approved By", readonly=True)
    admin_materials_approved_on = fields.Datetime(string="Admin Approved On", readonly=True)
    tailor_id = fields.Many2one("res.users", string="Assigned Tailor")

    product_id = fields.Many2one(
        "product.product",
        string="Product Type",
        domain=[("sale_ok", "=", True)],
        required=True,
    )

    garment_template = fields.Selection(
        [
            ("arabic_kandura", "Arabic Kandura"),
            ("kuwaiti_kandura", "Kuwaiti Kandura"),
        ],
        string="Garment Template",
        required=True,
        default="arabic_kandura",
    )

    quantity = fields.Integer(string="Quantity", default=1)
    order_date = fields.Datetime(string="Order Date", default=fields.Datetime.now)
    # ✅ NEW: Manufacturing start date
    manufacturing_started_on = fields.Datetime(
        string="Manufacturing Started On",
        readonly=True,
        copy=False,
        tracking=True,
    )

    # ✅ OPTIONAL (recommended): configurable lead time
    production_lead_time_days = fields.Float(
        string="Production Lead Time (Days)",
        default=10.0,
        tracking=True,
    )

    # ✅ Manual override (optional but useful)
    delivery_date_manual = fields.Datetime(
        string="Manual Delivery Date",
        copy=False,
        tracking=True,
    )

    # ✅ delivery_date becomes computed + stored (still editable)
    delivery_date = fields.Datetime(
        string="Delivery Date",
        compute="_compute_delivery_date",
        inverse="_inverse_delivery_date",
        store=True,
        tracking=True,
        readonly=False,
    )

    status = fields.Selection(
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
        string="Status",
        default="draft",
        tracking=True,
    )

    # -------------------- Status Actions (RESTORED) --------------------
    def action_set_pending(self):
        for order in self:
            if not (self._is_tailor() or self._is_admin()):
                raise UserError(_("Only Tailor/Production or Managers can change production statuses."))
            order.status = "cutting"

    def action_set_in_progress(self):
        for order in self:
            if not (self._is_tailor() or self._is_admin()):
                raise UserError(_("Only Tailor/Production or Managers can change production statuses."))
            order.status = "sewing"

    def action_set_qc(self):
        for order in self:
            if not (self._is_tailor() or self._is_qc() or self._is_admin()):
                raise UserError(_("Only Tailor/Production, QC, or Managers can move orders to Quality Inspection."))
            order.status = "qc"

    def action_set_ready_delivery(self):
        for order in self:
            if not (self._is_tailor() or self._is_qc() or self._is_admin()):
                raise UserError(_("Only Production/QC or Managers can set Ready for Delivery."))
            order.status = "ready_delivery"

    def action_set_done(self):
        for order in self:
            if not (self._is_sales() or self._is_admin()):
                raise UserError(_("Only Sales or Managers can mark the order as Delivered."))
            order.status = "delivered"

    def action_set_cancelled(self):
        for order in self:
            if not self._is_admin():
                raise UserError(_("Only Managers can cancel Tailor Orders."))
            order.status = "cancel"

    status_changed_on = fields.Datetime(string="Status Changed On", readonly=True)
    status_changed_by = fields.Many2one("res.users", string="Status Changed By", readonly=True)

    def _load_default_diagrams_if_missing(self):
        for order in self:
            if not order.arabic_diagram:
                order.arabic_diagram = _read_static_image("tailor_management", "arabic_kandura.png")
            if not order.kuwaiti_diagram:
                order.kuwaiti_diagram = _read_static_image("tailor_management", "kuwaiti_kandura.png")

    # -------------------- Measurements --------------------
    length = fields.Float(string="Length", digits=(6, 2))
    shoulder = fields.Float(string="Shoulder", digits=(6, 2))
    sleeve_length = fields.Float(string="Sleeve Length", digits=(6, 2))
    chest = fields.Float(string="Chest", digits=(6, 2))
    waist = fields.Float(string="Waist", digits=(6, 2))
    hip = fields.Float(string="Hip", digits=(6, 2))
    neck = fields.Float(string="Neck", digits=(6, 2))
    bottom_width = fields.Float(string="Bottom Width", digits=(6, 2))

    def action_open_ai_measure_wizard(self):
        """Open the AI measurement wizard, targeting this tailor order."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'AI Measurements',
            'res_model': 'tailor.ai.measure.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_target_model': 'tailor.order',
                'default_tailor_order_id': self.id,
                'default_partner_id': self.partner_id.id if self.partner_id else False,
            },
        }

    @api.depends("booking_date", "trial_date_manual", "trial_lead_time_days")
    def _compute_trial_date(self):
        for rec in self:
            # manual override wins
            if rec.trial_date_manual:
                rec.trial_date = rec.trial_date_manual
                continue

            if rec.booking_date:
                days = float(rec.trial_lead_time_days or 0.0)
                rec.trial_date = rec.booking_date + timedelta(days=days)
            else:
                rec.trial_date = False

    def _inverse_trial_date(self):
        for rec in self:
            rec.trial_date_manual = rec.trial_date

    @api.depends("booking_date", "order_date", "manufacturing_started_on", "production_lead_time_days",
                 "delivery_date_manual")
    def _compute_delivery_date(self):
        for rec in self:
            # Manual override always wins
            if rec.delivery_date_manual:
                rec.delivery_date = rec.delivery_date_manual
                continue

            base_dt = rec.manufacturing_started_on or rec.booking_date or rec.order_date

            if base_dt:
                days = float(rec.production_lead_time_days or 0.0)
                rec.delivery_date = base_dt + timedelta(days=days)

            else:
                rec.delivery_date = False

    def _inverse_delivery_date(self):
        for rec in self:
            rec.delivery_date_manual = rec.delivery_date

    def _set_manufacturing_started_if_needed(self, new_status=None):
        production_statuses = {"cutting", "sewing", "qc", "ready_delivery", "delivered"}
        for order in self:
            st = new_status or order.status
            if not order.manufacturing_started_on and st in production_statuses:
                order.manufacturing_started_on = fields.Datetime.now()

    # Style options
    front_design = fields.Selection(
        [("plain", "Plain"), ("design1", "Design Option 1"), ("design2", "Design Option 2")],
        string="Front Design",
    )
    sleeve_style = fields.Selection([("normal", "Normal"), ("other", "Other")], string="Sleeve Style")
    collar_style = fields.Selection(
        [("P1", "P1"), ("P2", "P2"), ("P3", "P3"), ("P4", "P4"), ("P5", "P5"), ("P6", "P6")],
        string="Collar Style",
    )
    cuff_style = fields.Selection([("A", "A"), ("B", "B"), ("C", "C"), ("D", "D"), ("E", "E")], string="Cuff Style")

    pocket_pen_big = fields.Boolean(string="Pen Pocket (Big)")
    pocket_pen_small = fields.Boolean(string="Pen Pocket (Small)")
    pocket_front = fields.Boolean(string="Front Pocket")
    pocket_key_left = fields.Boolean(string="Key Pocket (Left)")
    pocket_key_right = fields.Boolean(string="Key Pocket (Right)")

    fabric_deducted = fields.Boolean(default=False)

    buttons_type = fields.Selection([("normal", "Normal"), ("tich", "Tich"), ("zipper", "Zipper")],
                                    string="Buttons Type")
    stitching_type = fields.Selection([("normal", "Normal"), ("edge", "Edge")], string="Stitching Type")

    style_preference = fields.Text(string="Style Preference")
    fitting_style = fields.Char(string="Fitting Style")
    measurement_notes = fields.Text(string="Measurement Notes")

    # Fabric
    fabric_type = fields.Many2one(
        "product.product",
        string="Fabric Type",
        domain=[("type", "in", ("product", "consu"))],
    )

    # ✅ NEW: track if user manually set fabric_qty (so auto-compute won't overwrite)
    fabric_qty_is_manual = fields.Boolean(string="Fabric Qty Manual?", default=False)

    # ✅ UPDATED: fabric_qty auto-computed from measurements (stored), but can be overridden
    fabric_qty = fields.Float(
        string="Fabric Quantity (meters)",
        digits=(16, 2),
        compute="_compute_fabric_qty",
        inverse="_inverse_fabric_qty",
        store=True,
        readonly=False,
        default=1.0,
    )

    fabric_preference = fields.Char(string="Fabric Preference")

    # Delivery & Payment
    # Delivery & Payment
    booking_date = fields.Datetime(
        string="Booking Date",
        tracking=True,
        help="Date/time customer booked the order. Used to auto-calculate Trial Date."
    )

    # Trial interval (5.5 days)
    trial_lead_time_days = fields.Float(
        string="Trial Lead Time (Days)",
        default=5.0,
        tracking=True,
        help="Default trial date offset from Booking Date."
    )

    # Manual override (optional)
    trial_date_manual = fields.Datetime(
        string="Manual Trial Date",
        copy=False,
        tracking=True,
        help="If set, it overrides the automatic Trial Date."
    )

    # Computed trial date (editable)
    trial_date = fields.Datetime(
        string="Trial Date",
        compute="_compute_trial_date",
        inverse="_inverse_trial_date",
        store=True,
        tracking=True,
        readonly=False,
    )

    home_delivery = fields.Boolean(string="Home Delivery?")

    advance_payment_input = fields.Monetary(
        string="Advance Payment (Input)",
        currency_field="currency_input_id",
        default=0.0,
    )

    currency_input_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id,
        readonly=True,
    )

    currency_id = fields.Many2one(
        "res.currency",
        compute="_compute_currency_id",
        store=True,
        readonly=True,
    )

    advance_payment = fields.Monetary(
        string="Advance Payment",
        currency_field="currency_id",
        compute="_compute_advance_payment",
        inverse="_inverse_advance_payment",
        store=True,
    )

    balance = fields.Monetary(string="Balance", compute="_compute_balance", store=True)
    vat_amount = fields.Monetary(string="VAT ", compute="_compute_vat", store=True)

    customer_signature = fields.Binary(string="Customer Signature")
    salesperson_name = fields.Char(string="Salesperson Name")
    measurements_locked = fields.Boolean(string="Measurements Locked", default=False, tracking=True)

    # Quality Inspection
    qc_check_measurements = fields.Boolean(string="QC: Measurements Verified", tracking=True)
    qc_check_fabric = fields.Boolean(string="QC: Fabric Verified", tracking=True)
    qc_check_stitching = fields.Boolean(string="QC: Stitching Verified", tracking=True)
    qc_check_style = fields.Boolean(string="QC: Style/Design Verified", tracking=True)
    qc_check_finishing = fields.Boolean(string="QC: Finishing/Ironing Verified", tracking=True)
    qc_manager_comment = fields.Text(string="QC Manager Comment", tracking=True)

    qc_approved = fields.Boolean(string="QC Approved", default=False, tracking=True)
    qc_approved_by = fields.Many2one("res.users", string="QC Approved By", readonly=True)
    qc_approved_on = fields.Datetime(string="QC Approved On", readonly=True)

    # Relations
    mrp_ids = fields.One2many("mrp.production", "tailor_order_id", string="Manufacturing Orders")
    sale_order_id = fields.Many2one("sale.order", string="Related Sale Order")
    document_ids = fields.One2many("customer.documents", "tailor_order_id", string="Documents",
                                   order="upload_date desc")

    mrp_count = fields.Integer(string="MO Count", compute="_compute_counts", store=False)
    document_count = fields.Integer(string="Document Count", compute="_compute_counts", store=False)

    def _round_up(self, value, step):
        """Round up to nearest step (e.g., 0.25m)."""
        if not step or step <= 0:
            return value
        # ceil(value/step) * step without importing math
        q = int(value / step)
        if (q * step) < value:
            q += 1
        return q * step

    def _get_auto_fabric_qty(self):
        """
        Heuristic fabric meter calculator based on measurements.
        Assumption: measurements are in CM. Output in meters.
        Adjust coefficients if your tailoring rules differ.
        """
        self.ensure_one()

        def _to_m(v):
            v = max(float(v or 0.0), 0.0)
            # auto-detect unit:
            # >= 20  → centimeters
            # < 20   → meters
            return (v / 100.0) if v >= 20.0 else v

        L = _to_m(self.length)
        SL = _to_m(self.sleeve_length)
        C = _to_m(self.chest)
        BW = _to_m(self.bottom_width)

        # Basic sanity: if no useful measurements yet, keep default
        if L <= 0 and SL <= 0 and C <= 0 and BW <= 0:
            return float(self.fabric_qty or 1.0)

        # Template multiplier (tweak as needed)
        template_mult = 1.05 if self.garment_template == "arabic_kandura" else 1.10

        # Core estimate per 1 garment:
        # - L is the main driver
        # - sleeves add extra
        # - chest/bottom width add allowance
        # - +0.30 is general waste/hemming allowance
        per_piece = (L + (0.60 * SL) + (0.20 * C) + (0.20 * BW) + 0.30) * template_mult

        # Quantity
        total = per_piece * max(float(self.quantity or 1.0), 1.0)

        # Prefer rounding step from fabric UoM if available, else 0.25m
        # (Many setups use 0.01; 0.25 is more realistic for fabric cutting)
        step = 0.25

        total = self._round_up(total, step)

        # Never return <= 0
        return max(total, step)

    @api.depends(
        "garment_template",
        "quantity",
        "length",
        "shoulder",
        "sleeve_length",
        "chest",
        "waist",
        "hip",
        "neck",
        "bottom_width",
        "fabric_type",
    )
    def _compute_fabric_qty(self):
        """
        Auto compute fabric_qty unless user manually set it.
        """
        for rec in self:
            if rec.fabric_qty_is_manual:
                # Keep manual value
                continue
            rec.fabric_qty = rec._get_auto_fabric_qty()

    def _inverse_fabric_qty(self):
        """
        If a user edits fabric_qty directly, mark it as manual *only* for allowed roles.

        ✅ Business rule:
        - Tailors must NOT be able to override fabric consumption planning (prevents cheating / wrong issues).
        - Only Stock Manager or Tailor Admin can manually override, and only while the order is in Draft.
        """
        for rec in self:
            # Only Stock Manager / Admin can override
            if not (rec._is_admin() or rec._is_stock_manager()):
                raise UserError(_("Only Managers or Stock Managers can manually set Fabric Quantity."))
            # Only before confirmation
            if rec.status and rec.status != "draft":
                raise UserError(_("You can only override Fabric Quantity while the order is in Draft."))
            rec.fabric_qty_is_manual = True

    @api.onchange(
        "garment_template",
        "quantity",
        "length",
        "shoulder",
        "sleeve_length",
        "chest",
        "waist",
        "hip",
        "neck",
        "bottom_width",
        "fabric_type",
    )
    def _onchange_auto_fabric_qty(self):
        """
        In the form, update fabric_qty live while user edits measurements,
        but only if it's not manually overridden.
        """
        for rec in self:
            if rec.fabric_qty_is_manual:
                continue
            rec.fabric_qty = rec._get_auto_fabric_qty()

    def action_reset_fabric_qty_auto(self):
        """
        Optional helper button action if you want:
        Reset manual override and return to auto calculation.
        """
        for rec in self:
            rec.fabric_qty_is_manual = False
            rec.fabric_qty = rec._get_auto_fabric_qty()

    @api.constrains("sale_order_id")
    def _check_unique_sale_order(self):
        for rec in self:
            if rec.sale_order_id:
                count = self.search_count([
                    ("sale_order_id", "=", rec.sale_order_id.id),
                    ("id", "!=", rec.id),
                ])
                if count:
                    raise UserError(_("A Tailor Order already exists for this Sale Order!"))

    # =========================
    # COGS / Profitability Fields (FOR REPORTS)
    # =========================
    sale_price = fields.Monetary(
        string="Sale Price",
        currency_field="currency_id",
        compute="_compute_sale_price",
        store=True,
    )

    sale_amount = fields.Monetary(
        string="Sale Amount",
        currency_field="currency_id",
        compute="_compute_sale_amount",
        store=True,
    )

    # ✅ Store fabric cost as Monetary so SQL view can read it
    fabric_cost = fields.Monetary(
        string="Fabric Cost",
        currency_field="currency_id",
        compute="_compute_fabric_cost",
        store=True,
        readonly=True,
    )

    overhead_cost = fields.Monetary(
        string="Overhead Cost",
        currency_field="currency_id",
        default=0.0,
        help="Extra internal cost per order (labor, transport, utilities, etc.).",
    )

    cogs_total = fields.Monetary(
        string="COGS Total",
        currency_field="currency_id",
        compute="_compute_cogs_profit",
        store=True,
        readonly=True,
    )
    total_cogs = fields.Monetary(
        string="Total COGS",
        currency_field="currency_id",
        related="cogs_total",
        store=True,
    )

    gross_profit = fields.Monetary(
        string="Gross Profit",
        currency_field="currency_id",
        compute="_compute_cogs_profit",
        store=True,
        readonly=True,
    )

    @api.depends("sale_order_id.amount_total", "quantity", "product_id", "product_id.lst_price")
    def _compute_sale_price(self):
        """
        Prefer real Sale Order total.
        Fallback to product list price * qty.
        """
        for o in self:
            if o.sale_order_id:
                o.sale_price = float(o.sale_order_id.amount_total or 0.0)
            else:
                o.sale_price = float((o.product_id.lst_price or 0.0) * float(o.quantity or 0.0))

    @api.depends("sale_price")
    def _compute_sale_amount(self):
        for rec in self:
            rec.sale_amount = rec.sale_price or 0.0

    @api.depends("fabric_total_cost")
    def _compute_fabric_cost(self):
        """
        Use your already computed stored field: fabric_total_cost
        """
        for o in self:
            o.fabric_cost = float(o.fabric_total_cost or 0.0)

    @api.depends("sale_price", "fabric_cost", "overhead_cost")
    def _compute_cogs_profit(self):
        for o in self:
            cogs = float(o.fabric_cost or 0.0) + float(o.overhead_cost or 0.0)
            o.cogs_total = cogs
            o.gross_profit = float(o.sale_price or 0.0) - cogs

    def _compute_counts(self):
        for rec in self:
            rec.mrp_count = len(rec.mrp_ids)
            rec.document_count = len(rec.document_ids)
            rec.accessories_count = len(rec.accessory_line_ids)

    TEMPLATE_STYLE_RULES = {
        "arabic_kandura": {
            "front_design": {"plain", "design2"},
            "sleeve_style": {"normal"},
            "collar_style": {"P1", "P2", "P4", "P5", "P6"},
            "cuff_style": {"A", "B", "D", "E"},
            "buttons_type": {"normal", "zipper"},
            "stitching_type": {"normal"},
        },
        "kuwaiti_kandura": {
            "front_design": {"plain", "design1", "design2"},
            "sleeve_style": {"normal", "other"},
            "collar_style": {"P1", "P3"},
            "cuff_style": {"C", "D", "E"},
            "buttons_type": {"normal", "tich", "zipper"},
            "stitching_type": {"normal", "edge"},
        },
    }

    # Strict workflow
    ALLOWED_STATUS_TRANSITIONS = {
        "draft": {"confirmed", "cancel"},
        "confirmed": {"cutting", "cancel"},
        "cutting": {"sewing", "cancel"},
        "sewing": {"qc", "cancel"},
        "qc": {"ready_delivery", "sewing", "cancel"},
        "ready_delivery": {"delivered", "cancel"},
        "delivered": set(),
        "cancel": set(),
    }

    # RBAC helpers
    def _is_admin(self):
        return self.env.user.has_group("tailor_management.group_tailor_admin")

    def _is_sales(self):
        return self.env.user.has_group("tailor_management.group_tailor_sales")

    def _is_tailor(self):
        return self.env.user.has_group("tailor_management.group_tailor_tailor")

    def _is_qc(self):
        return self.env.user.has_group("tailor_management.group_tailor_qc") or self._is_admin()

    # ✅ ADDED: Stock Manager helper (for unlocking measurements)
    def _is_stock_manager(self):
        return self.env.user.has_group("stock.group_stock_manager")

    def _check_status_transition(self, old_status, new_status):
        if self._is_admin():
            return

        allowed = self.ALLOWED_STATUS_TRANSITIONS.get(old_status, set())
        if new_status not in allowed:
            raise UserError(_(
                "Invalid status change: '%s' → '%s'.\n"
                "You must follow the workflow steps (no skipping)."
            ) % (old_status, new_status))

        if old_status == "qc" and new_status == "ready_delivery" and not self.qc_approved:
            raise UserError(_("QC must be approved before setting Ready for Delivery."))

    # Currency/payment compute
    @api.depends("sale_order_id.currency_id", "currency_input_id")
    def _compute_currency_id(self):
        for rec in self:
            rec.currency_id = rec.sale_order_id.currency_id or rec.currency_input_id or rec.env.company.currency_id

    @api.depends("sale_order_id.advance_payment", "advance_payment_input", "sale_order_id")
    def _compute_advance_payment(self):
        for rec in self:
            if rec.sale_order_id:
                rec.advance_payment = rec.sale_order_id.advance_payment or 0.0
            else:
                rec.advance_payment = rec.advance_payment_input or 0.0

    def _inverse_advance_payment(self):
        for rec in self:
            if rec.sale_order_id:
                rec.sale_order_id.write({"advance_payment": rec.advance_payment or 0.0})
            else:
                rec.advance_payment_input = rec.advance_payment or 0.0

    # Diagrams
    def _ensure_default_diagrams(self):
        for rec in self:
            if not rec.arabic_diagram:
                rec.arabic_diagram = _default_arabic_diagram(rec)
            if not rec.kuwaiti_diagram:
                rec.kuwaiti_diagram = _default_kuwaiti_diagram(rec)

    def action_load_default_diagrams(self):
        self._ensure_default_diagrams()

    # Locations
    def _get_stock_locations(self):
        picking_type = self.env.ref("mrp.picking_type_manufacturing", raise_if_not_found=False)
        if picking_type and picking_type.default_location_src_id and picking_type.default_location_dest_id:
            return picking_type.default_location_src_id.id, picking_type.default_location_dest_id.id

        src = self.env["stock.location"].search([("usage", "=", "internal")], limit=1)
        dest = self.env["stock.location"].search([("usage", "=", "production")], limit=1)

        if not src or not dest:
            raise UserError(_("Could not find Stock/Production locations.\nPlease check Inventory configuration."))
        return src.id, dest.id

    # ============================================================
    # ✅ NEW (ADVANCED BUT SIMPLE): Fabric stock availability check
    # ============================================================
    def _get_available_qty_in_location(self, product, location_id, company=None):
        """
        Returns AVAILABLE quantity (on hand - reserved) for product in a location.
        Odoo-safe across versions:
        - Prefer stock.quant._get_available_quantity(...)
        - Fallback to product.with_context(location=...).free_qty / qty_available
        """
        product = product.with_company(company) if company else product
        location = self.env["stock.location"].browse(location_id)

        Quant = self.env["stock.quant"].sudo()
        try:
            # strict=True => only this exact location (no children)
            return float(Quant._get_available_quantity(product, location, strict=True))
        except Exception:
            # Fallbacks (safe)
            pctx = product.with_context(location=location_id)
            if hasattr(pctx, "free_qty"):
                return float(pctx.free_qty or 0.0)
            return float(pctx.qty_available or 0.0)

    def _check_fabric_stock_before_confirm(self):
        """
        Block confirmation if fabric is missing or not enough is available.
        This keeps logic clean: No fabric => no confirmation => no fake production.
        """
        for order in self:
            # Must have fabric + qty
            if not order.fabric_type:
                raise UserError(_("Please select Fabric Type before confirming the order."))
            if float(order.fabric_qty or 0.0) <= 0.0:
                raise UserError(_("Fabric Quantity (meters) must be greater than zero before confirming the order."))

            src_loc_id, _dest_loc_id = order._get_stock_locations()

            available = order._get_available_qty_in_location(
                order.fabric_type,
                src_loc_id,
                company=order.company_id,
            )
            required = float(order.fabric_qty or 0.0)

            # Compare using product UoM rounding (best practice)
            rounding = getattr(order.fabric_type.uom_id, "rounding", 0.01) or 0.01
            if float_compare(available, required, precision_rounding=rounding) < 0:
                loc_name = self.env["stock.location"].browse(src_loc_id).display_name
                raise UserError(_(
                    "Not enough fabric in stock to confirm this order.\n\n"
                    "Fabric: %(fabric)s\n"
                    "Location: %(loc)s\n"
                    "Required: %(req)s\n"
                    "Available: %(avail)s\n\n"
                    "Please replenish fabric or adjust Fabric Quantity."
                ) % {
                                    "fabric": order.fabric_type.display_name,
                                    "loc": loc_name,
                                    "req": required,
                                    "avail": available,
                                })

    # Activities
    def _users_in_group(self, group_xmlid):
        group = self.env.ref(group_xmlid, raise_if_not_found=False)
        if not group:
            return self.env["res.users"]
        if hasattr(group, "user_ids"):
            return group.user_ids
        if hasattr(group, "users"):
            return group.users
        return self.env["res.users"]

    def _schedule_activity_for_users(self, users, summary, note):
        activity_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        if not activity_type:
            return

        for order in self:
            for user in users:
                order.activity_schedule(
                    activity_type_id=activity_type.id,
                    user_id=user.id,
                    summary=summary,
                    note=note,
                    date_deadline=fields.Date.today(),
                )

    def _schedule_stage_activity(self, stage):
        for order in self:
            if stage == "confirmed":
                users = order._users_in_group("tailor_management.group_tailor_tailor")
                order._schedule_activity_for_users(
                    users,
                    summary=f"Start Production ({order.name})",
                    note="Order is confirmed. Start cutting/sewing and update the workflow.",
                )

            elif stage == "qc":
                users = order._users_in_group("tailor_management.group_tailor_qc")
                order._schedule_activity_for_users(
                    users,
                    summary=f"QC Required ({order.name})",
                    note="Please verify measurements, fabric, stitching, finishing and approve QC.",
                )

            elif stage == "ready_delivery":
                users = order._users_in_group("tailor_management.group_tailor_sales")
                order._schedule_activity_for_users(
                    users,
                    summary=f"Create Invoice ({order.name})",
                    note="Order is Ready for Delivery. Please create the invoice and arrange the delivery handover.",
                )

            elif stage == "delivered":
                users = order._users_in_group("tailor_management.group_tailor_admin")
                order._schedule_activity_for_users(
                    users,
                    summary=f"Check Delivery ({order.name})",
                    note="Order is marked Delivered. Please verify delivery completion and archive/save documents.",
                )

    # ✅ NEW: Auto subscribe followers for the order
    def _auto_subscribe_order_followers(self):
        for order in self:
            partner_ids = set()
            if order.partner_id:
                partner_ids.add(order.partner_id.id)
            if order.tailor_id and order.tailor_id.partner_id:
                partner_ids.add(order.tailor_id.partner_id.id)
            if self.env.user.partner_id:
                partner_ids.add(self.env.user.partner_id.id)
            if partner_ids:
                order.message_subscribe(list(partner_ids))

    def action_fix_required_document_names(self):
        Document = self.env["customer.documents"].sudo()

        is_ar = (self.env.context.get("lang") or self.env.user.lang or "").startswith("ar")

        fix_map_ar = {
            "measurement": "قياسات العميل",
            "contract": "عقد / اتفاق العميل",
            "invoice": "فاتورة / إيصال",
            "design": "صور التصميم / المرجع",
            "accessories": "قائمة الإكسسوارات / الإضافات",
        }

        fix_map_en = {
            "measurement": "Customer Measurements",
            "contract": "Customer Contract / Agreement",
            "invoice": "Invoice / Receipt",
            "design": "Design / Reference Images",
            "accessories": "Accessories / Extras List",
        }

        fix_map = fix_map_ar if is_ar else fix_map_en

        for order in self:
            docs = Document.search([
                ("tailor_order_id", "=", order.id),
                ("is_required", "=", True),
                ("document_type", "in", list(fix_map.keys())),
            ])
            for d in docs:
                new_name = fix_map.get(d.document_type)
                if new_name and d.name != new_name:
                    d.write({"name": new_name})

    # ✅ NEW: Auto create documents + activities for the order
    def _auto_create_required_documents_and_activities(self):
        Document = self.env["customer.documents"].sudo()
        mt_note = self.env.ref("mail.mt_note", raise_if_not_found=False)

        is_ar = (self.env.context.get("lang") or self.env.user.lang or "").startswith("ar")

        default_docs = [
            ("قياسات العميل" if is_ar else "Customer Measurements", "measurement",
             "tailor_management.group_tailor_admin"),
            ("عقد / اتفاق العميل" if is_ar else "Customer Contract / Agreement", "contract",
             "tailor_management.group_tailor_admin"),
            ("فاتورة / إيصال" if is_ar else "Invoice / Receipt", "invoice", "tailor_management.group_tailor_sales"),
            ("صور التصميم / المرجع" if is_ar else "Design / Reference Images", "design",
             "tailor_management.group_tailor_tailor"),
            ("قائمة الإكسسوارات / الإضافات" if is_ar else "Accessories / Extras List", "accessories",
             "tailor_management.group_tailor_tailor"),
        ]

        for order in self:
            for doc_name, doc_type, group_xmlid in default_docs:
                exists = Document.search_count([
                    ("tailor_order_id", "=", order.id),
                    ("document_type", "=", doc_type),
                    ("is_required", "=", True),
                ])
                if exists:
                    continue

                doc = Document.create({
                    "name": doc_name,
                    "document_type": doc_type,
                    "partner_id": order.partner_id.id,
                    "tailor_order_id": order.id,
                    "is_required": True,
                })

                order.message_post(
                    body=f"<b>Required Document Created</b>: {doc.name} ({doc.document_type})",
                    message_type="comment",
                    subtype_id=mt_note.id if mt_note else False,
                )

                users = order._users_in_group(group_xmlid)
                if users:
                    doc._schedule_document_activity(
                        users,
                        summary=f"Upload Document: {doc.name}",
                        note=f"Upload/attach '{doc.name}' for Tailor Order: {order.name}",
                    )

    # Customer approval
    def approve_order(self):
        for order in self:
            # ✅ Sales can record customer approval, but MUST NOT push the flow into manufacturing.
            # Stock checking/reservation + confirmation is done by Stock Manager/Admin.
            order.with_context(skip_sales_guard=True).write({
                "customer_approved": True,
            })

    # ------------------------------------------------------------
    # Materials gate actions
    # ------------------------------------------------------------
    def action_check_and_confirm(self):
        """Stock Manager/Admin checks availability, reserves stock, then confirms the order.

        This is the ONLY path that should unlock production.
        """
        for order in self:
            if not (order._is_stock_manager() or order._is_admin()):
                raise UserError(_("Only Stock Managers or Managers can check availability and confirm."))

            if order.status != "draft":
                raise UserError(_("You can only confirm after stock check while the order is in Draft."))

            if not order.customer_approved:
                raise UserError(_("Customer approval is required before stock confirmation."))

            # 1) Check fabric stock (your existing logic)
            order._check_fabric_stock_before_confirm()

            # 2) Confirm + mark stock checked
            order.with_context(skip_sales_guard=True).write({
                "status": "confirmed",
                "stock_checked": True,
                "stock_checked_by": self.env.user.id,
                "stock_checked_on": fields.Datetime.now(),
            })

            # 3) Reserve materials on linked MOs immediately (if any)
            for mo in order.mrp_ids:
                if hasattr(mo, "action_assign"):
                    mo.sudo().action_assign()

    def action_admin_approve_materials(self):
        """Admin/Manager final approval before tailoring starts."""
        for order in self:
            if not order._is_admin():
                raise UserError(_("Only Managers can approve materials for production."))
            if order.status != "confirmed":
                raise UserError(_("Materials approval can only be done after stock confirmation."))
            if not order.stock_checked:
                raise UserError(_("Stock must be checked/reserved by Stock Manager before admin approval."))

            order.sudo().write({
                "admin_materials_approved": True,
                "admin_materials_approved_by": self.env.user.id,
                "admin_materials_approved_on": fields.Datetime.now(),
            })

    # Autofill measurements
    @api.onchange("partner_id", "garment_template")
    def _onchange_partner_id(self):
        if not self.partner_id:
            return

        domain = [("partner_id", "=", self.partner_id.id)]
        measurement = False

        if self.garment_template:
            measurement = self.env["customer.measurements"].search(
                domain + [("garment_template", "=", self.garment_template)],
                order="create_date desc, id desc",
                limit=1,
            )
        if not measurement:
            measurement = self.env["customer.measurements"].search(
                domain,
                order="create_date desc, id desc",
                limit=1,
            )
        if not measurement:
            return

        self.length = measurement.length
        self.shoulder = measurement.shoulder
        self.sleeve_length = measurement.sleeve_length
        self.chest = measurement.chest
        self.waist = measurement.waist
        self.hip = measurement.hip
        self.neck = measurement.neck
        self.bottom_width = measurement.bottom_width
        self.fabric_preference = measurement.fabric_preference

    # Create
    @api.model_create_multi
    def create(self, vals_list):
        new_vals_list = []
        for vals in vals_list:
            vals = dict(vals)
            if not vals.get("name"):
                vals["name"] = self.env["ir.sequence"].next_by_code("tailor.order") or "TO/Unknown"
            new_vals_list.append(vals)

        records = super(TailorOrder, self).create(new_vals_list)
        records._ensure_default_diagrams()

        records._auto_subscribe_order_followers()
        records._auto_create_required_documents_and_activities()
        records.action_fix_required_document_names()

        stock_users = records._users_in_group("stock.group_stock_manager")
        if stock_users:
            records._schedule_activity_for_users(
                stock_users,
                summary="New Tailor Order Created",
                note="A new Tailor Order was created. Please review fabric availability and prepare stock if needed.",
            )

        return records

    # Sale + MO generation (kept)
    def generate_sale_and_mo(self):
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_("Customer is required to create a Sale Order."))
        if not self.product_id:
            raise UserError(_("Please select a product."))

        SaleOrder = self.env["sale.order"]
        if self.sale_order_id:
            return

        vals = {
            "partner_id": self.partner_id.id,
            "delivery_date": self.delivery_date,
            "advance_payment": self.advance_payment_input or 0.0,
            "order_line": [(0, 0, {
                "product_id": self.product_id.id,
                "product_uom_qty": self.quantity or 1,
                "price_unit": self.product_id.lst_price,
            })],
        }

        if "commitment_date" in SaleOrder._fields and self.delivery_date:
            vals["commitment_date"] = self.delivery_date

        sale_order = SaleOrder.create(vals)
        self.with_context(skip_sales_guard=True).write({"sale_order_id": sale_order.id})
        sale_order.write({"advance_payment": self.advance_payment_input or 0.0})

    def _prepare_accessory_moves_for_mo(self, mo):
        """
        Create additional raw material moves on MO for accessory_line_ids.
        This makes accessories follow the order into manufacturing.
        """
        self.ensure_one()

        if not self.accessory_line_ids:
            return
        if self.accessories_pushed_to_mo:
            return

        totals = {}
        for line in self.accessory_line_ids:
            if not line.product_id:
                continue
            qty = float(line.quantity or 0.0)
            if qty <= 0:
                continue
            totals.setdefault(line.product_id.id, 0.0)
            totals[line.product_id.id] += qty

        if not totals:
            return

        src_loc_id, dest_loc_id = self._get_stock_locations()
        picking_type = self.env.ref("mrp.picking_type_manufacturing", raise_if_not_found=False)

        StockMove = self.env["stock.move"].sudo()
        for product_id, qty in totals.items():
            product = self.env["product.product"].browse(product_id)

            move_vals = {
                "product_id": product.id,
                "product_uom_qty": qty,
                "company_id": self.company_id.id,
                "location_id": src_loc_id,
                "location_dest_id": dest_loc_id,
            }

            if "name" in StockMove._fields:
                move_vals["name"] = f"Accessories for {self.name}"
            elif "description_picking" in StockMove._fields:
                move_vals["description_picking"] = f"Accessories for {self.name}"

            if "product_uom" in StockMove._fields:
                move_vals["product_uom"] = product.uom_id.id
            if "product_uom_id" in StockMove._fields:
                move_vals["product_uom_id"] = product.uom_id.id

            if picking_type and "picking_type_id" in StockMove._fields:
                move_vals["picking_type_id"] = picking_type.id

            if "tailor_order_id" in StockMove._fields:
                move_vals["tailor_order_id"] = self.id

            if "move_raw_ids" in mo._fields:
                mo_move_vals = dict(move_vals)
                mo.sudo().write({"move_raw_ids": [(0, 0, mo_move_vals)]})
            else:
                if "raw_material_production_id" in StockMove._fields:
                    move_vals["raw_material_production_id"] = mo.id
                elif "production_id" in StockMove._fields:
                    move_vals["production_id"] = mo.id

                move = StockMove.create(move_vals)

                if hasattr(move, "_action_confirm"):
                    move._action_confirm()
                if hasattr(move, "_action_assign"):
                    move._action_assign()

        self.with_context(skip_sales_guard=True).write({"accessories_pushed_to_mo": True})

    def generate_manufacturing_order(self):
        self.ensure_one()
        MrpProduction = self.env["mrp.production"]
        MrpBom = self.env["mrp.bom"]

        if not self.product_id:
            raise UserError(_("Please select a garment product to create Manufacturing Order!"))
        if (self.quantity or 0) <= 0:
            raise UserError(_("Quantity must be greater than zero to create a Manufacturing Order."))

        bom = MrpBom.search([
            "|",
            ("product_id", "=", self.product_id.id),
            ("product_tmpl_id", "=", self.product_id.product_tmpl_id.id),
        ], limit=1)

        mo_vals = {
            "product_id": self.product_id.id,
            "product_qty": float(self.quantity or 1.0),
            "product_uom_id": self.product_id.uom_id.id,
            "origin": self.name,
        }

        if "sale_order_id" in MrpProduction._fields and self.sale_order_id:
            mo_vals["sale_order_id"] = self.sale_order_id.id
        if "tailor_order_id" in MrpProduction._fields:
            mo_vals["tailor_order_id"] = self.id
        if "is_tailoring_order" in MrpProduction._fields:
            mo_vals["is_tailoring_order"] = True

        if bom:
            mo_vals["bom_id"] = bom.id

        if not bom:
            if not self.fabric_type:
                raise UserError(_("Please select a Fabric/Product to create Manufacturing Order (or create a BOM)!"))

            src_loc_id, dest_loc_id = self._get_stock_locations()

            if "move_raw_ids" in MrpProduction._fields:
                StockMove = self.env["stock.move"]
                move_vals = {"product_id": self.fabric_type.id, "product_uom_qty": self.fabric_qty or 1.0}

                if "product_uom" in StockMove._fields:
                    move_vals["product_uom"] = self.fabric_type.uom_id.id
                if "product_uom_id" in StockMove._fields:
                    move_vals["product_uom_id"] = self.fabric_type.uom_id.id
                if "location_id" in StockMove._fields:
                    move_vals["location_id"] = src_loc_id
                if "location_dest_id" in StockMove._fields:
                    move_vals["location_dest_id"] = dest_loc_id
                if "name" in StockMove._fields:
                    move_vals["name"] = f"Fabric for {self.name}"

                mo_vals["move_raw_ids"] = [(0, 0, move_vals)]

        mo = MrpProduction.create(mo_vals)
        self.mrp_ids = [(4, mo.id)]

        if hasattr(mo, "action_confirm"):
            mo.action_confirm()

        # ✅ Reserve / check raw materials immediately (done by Stock Manager at confirmation time)
        # This prevents Tailors from being the ones who 'check availability' later.
        if hasattr(mo, "action_assign"):
            try:
                mo.action_assign()
            except Exception:
                # Some versions may not support it; ignore safely
                pass

        self._prepare_accessory_moves_for_mo(mo)

        if bom and self.fabric_type and self.fabric_qty and getattr(mo, "move_raw_ids", False):
            fabric_move = mo.move_raw_ids.filtered(lambda m: m.product_id.id == self.fabric_type.id)[:1]
            if fabric_move:
                fabric_move.write({"product_uom_qty": self.fabric_qty})

    # Sales guard
    def _guard_sales_write_rules(self, order, vals):
        if self.env.context.get("skip_sales_guard"):
            return
        if self._is_admin():
            return
        if not self._is_sales():
            return

        qc_fields = {
            "qc_check_measurements", "qc_check_fabric", "qc_check_stitching", "qc_check_style", "qc_check_finishing",
            "qc_manager_comment", "qc_approved", "qc_approved_by", "qc_approved_on",
        }
        if qc_fields.intersection(vals.keys()):
            raise UserError(_("Salesperson cannot edit QC fields."))

        if vals.get("status") == "cancel":
            raise UserError(_("Salesperson cannot cancel Tailor Orders."))

        if "status" in vals:
            new_status = vals.get("status")

            if new_status == "confirmed":
                if order.status != "draft":
                    raise UserError(_("Salesperson can only confirm while the order is in Draft."))

            elif new_status == "delivered":
                if order.status != "ready_delivery":
                    raise UserError(_("Salesperson can only mark Delivered when the order is Ready for Delivery."))

            else:
                raise UserError(_("Salesperson can only Confirm or Mark Delivered."))

        if order.status != "draft":
            other_fields = set(vals.keys()) - {"status", "status_changed_on", "status_changed_by",
                                               "measurements_locked"}
            if other_fields:
                raise UserError(_("Salesperson can edit details only while the order is in Draft."))

    # Stock move (kept)
    def _update_fabric_stock(self):
        StockMove = self.env["stock.move"].sudo()
        for order in self:
            if order.status != "confirmed":
                continue
            if not order.fabric_type or (order.fabric_qty or 0.0) <= 0:
                continue
            if order.fabric_deducted:
                continue

            if getattr(order.fabric_type, "tracking", "none") != "none":
                raise UserError(_(
                    "This fabric product is Lot/Serial tracked.\n"
                    "Odoo requires selecting a Lot/Serial number to validate the stock move.\n"
                    "Please consume this fabric through a Picking/MO where you can choose the lot."
                ))

            src_loc_id, dest_loc_id = order._get_stock_locations()
            picking_type = self.env.ref("mrp.picking_type_manufacturing", raise_if_not_found=False)

            move_vals = {
                "product_id": order.fabric_type.id,
                "product_uom_qty": order.fabric_qty,
                "location_id": src_loc_id,
                "location_dest_id": dest_loc_id,
                "origin": order.name,
                "company_id": order.company_id.id,
            }

            if "name" in StockMove._fields:
                move_vals["name"] = f"Fabric usage for {order.name}"
            elif "description_picking" in StockMove._fields:
                move_vals["description_picking"] = f"Fabric usage for {order.name}"

            if "product_uom" in StockMove._fields:
                move_vals["product_uom"] = order.fabric_type.uom_id.id
            if "product_uom_id" in StockMove._fields:
                move_vals["product_uom_id"] = order.fabric_type.uom_id.id

            if picking_type and "picking_type_id" in StockMove._fields:
                move_vals["picking_type_id"] = picking_type.id

            if "tailor_order_id" in StockMove._fields:
                move_vals["tailor_order_id"] = order.id

            move = StockMove.create(move_vals)

            if hasattr(move, "_action_confirm"):
                move._action_confirm()
            if hasattr(move, "_action_assign"):
                move._action_assign()

            if "quantity_done" in move._fields:
                move.quantity_done = order.fabric_qty

            if hasattr(move, "_action_done"):
                move._action_done()

    # write()
    def write(self, vals):
        locked_fields = {
            "length", "shoulder", "sleeve_length", "chest", "waist", "hip", "neck", "bottom_width",
            "front_design", "sleeve_style", "collar_style", "cuff_style", "buttons_type", "stitching_type",
            "pocket_pen_big", "pocket_pen_small", "pocket_front", "pocket_key_left", "pocket_key_right",
            "style_preference", "fitting_style", "measurement_notes", "fabric_preference",
            "fabric_type", "fabric_qty",
            "accessory_line_ids",
            "accessories_notes",
            "fabric_unit_cost",
        }

        for order in self:
            self._guard_sales_write_rules(order, vals)

            # ✅ Prevent Tailor users from changing fabric planning fields (anti-cheat / correct roles)
            if self._is_tailor() and not self._is_admin():
                protected = {"fabric_type", "fabric_qty", "fabric_qty_is_manual", "accessory_line_ids"}
                if protected.intersection(vals.keys()):
                    raise UserError(_("Tailors are not allowed to change Fabric/Accessories planning fields.\n"
                                      "Please ask Sales/Stock Manager to adjust materials."))

            qc_fields = {
                "qc_check_measurements", "qc_check_fabric", "qc_check_stitching", "qc_check_style",
                "qc_check_finishing",
                "qc_manager_comment", "qc_approved", "qc_approved_by", "qc_approved_on",
            }
            if qc_fields.intersection(vals.keys()) and not (self._is_qc() or self._is_admin()):
                raise UserError(_("Only QC or Managers can edit Quality Inspection fields."))

            if "status" in vals and not self._is_admin():
                new_status = vals.get("status")

                # ✅ HARD RULE: Only Stock Manager / Managers can CONFIRM (stock reservation & integrity)
                if new_status == "confirmed" and not self._is_stock_manager():
                    # Admin already excluded above; here it's non-admin users
                    raise UserError(_("Only Stock Managers or Managers can confirm an order.\n"
                                      "Sales can create Draft orders; Tailors can only work after stock confirmation."))

                if new_status in ["cutting", "sewing"] and not self._is_tailor():
                    raise UserError(_("Only Tailor/Production users can set Cutting/Sewing statuses."))

                # ✅ HARD GATE: Production cannot start until BOTH stock check and admin approval are done
                if new_status in ["cutting", "sewing"]:
                    if not order.stock_checked:
                        raise UserError(_(
                            "Production cannot start yet.\n"
                            "Stock Manager must Check & Reserve Materials first."
                        ))
                    if not order.admin_materials_approved:
                        raise UserError(_(
                            "Production cannot start yet.\n"
                            "A Manager must Approve Materials first."
                        ))

                if new_status == "qc" and not (self._is_tailor() or self._is_qc()):
                    raise UserError(
                        _("Only Tailor/Production, QC, or Managers can move an order to Quality Inspection."))

                if new_status == "ready_delivery" and not (self._is_tailor() or self._is_qc()):
                    raise UserError(_("Only Production/QC or Managers can set Ready for Delivery."))

                if new_status == "delivered" and not (self._is_sales() or self._is_admin()):
                    raise UserError(_("Only Sales or Managers can mark the order as Delivered."))

                if new_status == "cancel":
                    raise UserError(_("Only Managers can cancel Tailor Orders."))

            if "status" in vals:
                new_status = vals.get("status")
                if new_status and new_status != order.status:
                    order._check_status_transition(order.status, new_status)
                # ✅ NEW: set manufacturing start date once when production begins
                if new_status in ["cutting", "sewing", "qc", "ready_delivery", "delivered"]:
                    order.sudo()._set_manufacturing_started_if_needed(new_status=new_status)

                # ✅ ADDED: Block confirmation if fabric not available
                if new_status == "confirmed":
                    order._check_fabric_stock_before_confirm()

        if "status" in vals:
            vals = dict(vals)
            vals["status_changed_on"] = fields.Datetime.now()
            vals["status_changed_by"] = self.env.user.id

        if "status" in vals and vals.get("status") in ["sewing", "cutting", "draft", "cancel"]:
            vals = dict(vals)
            vals.update({"qc_approved": False, "qc_approved_by": False, "qc_approved_on": False})

        if "measurements_locked" in vals and not (self._is_admin() or self._is_stock_manager()):
            raise UserError(_("Only Managers or Stock Managers can lock/unlock measurements!"))

        for order in self:
            if order.measurements_locked and locked_fields.intersection(vals.keys()):
                if not (self._is_admin() or self._is_stock_manager()):
                    raise UserError(_("Measurements and style selections are locked.\nAsk a manager to unlock them."))

        if vals.get("status") == "confirmed":
            vals = dict(vals)
            vals["measurements_locked"] = True

        res = super(TailorOrder, self).write(vals)

        # ✅ Customer-only email on key status changes
        if "status" in vals:
            new_status = vals.get("status")
            if new_status in ["confirmed", "ready_delivery", "delivered"]:
                template = self.env.ref("tailor_management.email_template_tailor_order_status",
                                        raise_if_not_found=False)
                if template:
                    for order in self:
                        if order.partner_id and order.partner_id.email:
                            template.sudo().send_mail(order.id, force_send=True)

        if "garment_template" in vals or "arabic_diagram" in vals or "kuwaiti_diagram" in vals:
            self._ensure_default_diagrams()

        if "status" in vals:
            new_status = vals.get("status")
            if new_status in ["confirmed", "qc", "ready_delivery", "delivered"]:
                self._schedule_stage_activity(new_status)

        if vals.get("status") == "confirmed":
            for order in self.with_context(skip_sales_guard=True):
                if not order.sale_order_id:
                    order.generate_sale_and_mo()

                order._save_measurements_snapshot()

                if not order.mrp_ids:
                    origins = [order.name]
                    if order.sale_order_id and order.sale_order_id.name:
                        origins.append(order.sale_order_id.name)

                    existing_mo = self.env["mrp.production"].search([("origin", "in", origins)], limit=1)
                    if existing_mo:
                        order.write({"mrp_ids": [(4, existing_mo.id)]})
                        if "tailor_order_id" in existing_mo._fields and not existing_mo.tailor_order_id:
                            existing_mo.write({"tailor_order_id": order.id})
                    else:
                        order.generate_manufacturing_order()

                if not order.fabric_deducted:
                    if order.mrp_ids:
                        order.write({"fabric_deducted": True})
                    else:
                        order._update_fabric_stock()
                        order.write({"fabric_deducted": True})

        return res

    def unlock_measurements(self):
        if not (self._is_admin() or self._is_stock_manager()):
            raise UserError(_("Only Managers or Stock Managers can unlock measurements!"))
        super(TailorOrder, self).write({"measurements_locked": False, "status": "draft"})

    def lock_measurements(self):
        if not (self._is_admin() or self._is_stock_manager()):
            raise UserError(_("Only Managers or Stock Managers can lock measurements!"))
        super(TailorOrder, self).write({"measurements_locked": True})

    @api.depends("sale_order_id.amount_total", "advance_payment")
    def _compute_balance(self):
        for order in self:
            total = order.sale_order_id.amount_total if order.sale_order_id else 0.0
            order.balance = total - (order.advance_payment or 0.0)

    @api.depends("sale_order_id.amount_total", "sale_order_id.amount_tax", "sale_order_id.amount_untaxed")
    def _compute_vat(self):
        for order in self:
            if order.sale_order_id:
                tax = getattr(order.sale_order_id, "amount_tax", 0.0) or 0.0
                if tax:
                    order.vat_amount = tax
                else:
                    base = getattr(order.sale_order_id, "amount_untaxed",
                                   0.0) or order.sale_order_id.amount_total or 0.0
                    order.vat_amount = base * 0.05
            else:
                order.vat_amount = 0.0

    @api.onchange("garment_template")
    def _onchange_garment_template(self):
        self._ensure_default_diagrams()

        if self.garment_template == "arabic_kandura":
            self.front_design = "plain"
            self.sleeve_style = "normal"
            self.collar_style = "P1"
            self.cuff_style = "A"
            self.buttons_type = "normal"
            self.stitching_type = "normal"

        elif self.garment_template == "kuwaiti_kandura":
            self.front_design = "design1"
            self.sleeve_style = "other"
            self.collar_style = "P3"
            self.cuff_style = "C"
            self.buttons_type = "tich"
            self.stitching_type = "edge"

    @api.constrains("length", "shoulder", "sleeve_length", "chest", "waist", "hip", "neck", "bottom_width")
    def _check_measurements_positive(self):
        for order in self:
            for field in ["length", "shoulder", "sleeve_length", "chest", "waist", "hip", "neck", "bottom_width"]:
                value = getattr(order, field)
                if value and value <= 0:
                    raise UserError(_("%s must be greater than zero." % field.replace("_", " ").title()))

    @api.constrains("garment_template", "front_design", "sleeve_style", "collar_style", "cuff_style",
                    "buttons_type", "stitching_type")
    def _check_template_style_rules(self):
        for order in self:
            rules = self.TEMPLATE_STYLE_RULES.get(order.garment_template)
            if not rules:
                continue

            def _check(field_name):
                allowed = rules.get(field_name)
                val = getattr(order, field_name)
                if allowed and val and val not in allowed:
                    raise UserError(
                        _("Value '%s' is not allowed for '%s' when template is '%s'.")
                        % (
                            val,
                            field_name.replace("_", " ").title(),
                            dict(self._fields["garment_template"].selection).get(order.garment_template),
                        )
                    )

            _check("front_design")
            _check("sleeve_style")
            _check("collar_style")
            _check("cuff_style")
            _check("buttons_type")
            _check("stitching_type")

    @api.depends("garment_template", "arabic_diagram", "kuwaiti_diagram")
    def _compute_display_diagram(self):
        for order in self:
            order.display_diagram = order.arabic_diagram if order.garment_template == "arabic_kandura" else order.kuwaiti_diagram

    def _save_measurements_snapshot(self):
        for order in self:
            if order.sale_order_id:
                existing = self.env["customer.measurements"].search([("sale_order_id", "=", order.sale_order_id.id)],
                                                                    limit=1)
                if existing:
                    continue

            self.env["customer.measurements"].create(
                {
                    "partner_id": order.partner_id.id,
                    "sale_order_id": order.sale_order_id.id if order.sale_order_id else False,
                    "garment_template": order.garment_template,
                    "measurement_date": fields.Date.today(),
                    "length": order.length,
                    "shoulder": order.shoulder,
                    "sleeve_length": order.sleeve_length,
                    "chest": order.chest,
                    "waist": order.waist,
                    "hip": order.hip,
                    "neck": order.neck,
                    "bottom_width": order.bottom_width,
                    "fabric_preference": order.fabric_preference,
                    "style_preference": order.style_preference,
                    "fitting_style": order.fitting_style,
                    "measurement_notes": order.measurement_notes,
                }
            )

    def action_qc_approve(self):
        for order in self:
            if not (self._is_qc() or self._is_admin()):
                raise UserError(_("Only QC or Managers can approve Quality Inspection!"))

            if order.status != "qc":
                raise UserError(_("QC approval can only be done when the order is in Quality Inspection stage."))

            required = [
                order.qc_check_measurements,
                order.qc_check_fabric,
                order.qc_check_stitching,
                order.qc_check_style,
                order.qc_check_finishing,
            ]
            if not all(required):
                raise UserError(_("Please complete all QC checklist items before approving."))

            order.write({
                "qc_approved": True,
                "qc_approved_by": self.env.user.id,
                "qc_approved_on": fields.Datetime.now(),
            })

            users = order._users_in_group("tailor_management.group_tailor_tailor")
            order._schedule_activity_for_users(
                users,
                summary=f"Produce / Finish Order ({order.name})",
                note="QC is approved. Please complete production and set the order to Ready for Delivery.",
            )

    @api.onchange("fabric_type")
    def _onchange_fabric_type_cost(self):
        if self.fabric_type:
            self.fabric_unit_cost = float(self.fabric_type.standard_price or 0.0)


# -------------------- Tailor Accessories / Extras (Lines) --------------------
class TailorAccessoryLine(models.Model):
    _name = "tailor.accessory.line"
    _description = "Tailor Accessories / Extras"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)

    tailor_order_id = fields.Many2one(
        "tailor.order",
        string="Tailor Order",
        required=True,
        ondelete="cascade",
        index=True,
    )

    product_id = fields.Many2one(
        "product.product",
        string="Accessory / Extra",
        domain=[("type", "in", ("product", "consu"))],
        required=True,
    )

    quantity = fields.Float(string="Qty", default=1.0)
    uom_id = fields.Many2one("uom.uom", string="UoM", related="product_id.uom_id", readonly=True)

    accessory_type = fields.Selection(
        [
            ("buttons", "Buttons"),
            ("zipper", "Zipper"),
            ("lining", "Lining"),
            ("embroidery", "Embroidery"),
            ("logo", "Logo/Branding"),
            ("patch", "Patch"),
            ("thread", "Thread"),
            ("other", "Other"),
        ],
        string="Type",
        default="other",
    )

    color = fields.Char(string="Color")
    size = fields.Char(string="Size")
    notes = fields.Text(string="Notes / Design Instruction")

    customer_provided = fields.Boolean(string="Customer Provided", default=False)
    is_required = fields.Boolean(string="Required", default=True)


# -------------------- Extend Res Partner --------------------
class ResPartner(models.Model):
    _inherit = "res.partner"
    measurements_ids = fields.One2many("customer.measurements", "partner_id", string="Tailor Measurements")


# -------------------- Customer Measurements --------------------
class CustomerMeasurements(models.Model):
    _name = "customer.measurements"
    _description = "Customer Tailor Measurements"
    _rec_name = "display_name"
    _order = "create_date desc, id desc"

    partner_id = fields.Many2one("res.partner", string="Customer", required=True)
    sale_order_id = fields.Many2one("sale.order", string="Sale Order")

    garment_template = fields.Selection(
        [("arabic_kandura", "Arabic Kandura"), ("kuwaiti_kandura", "Kuwaiti Kandura")],
        string="Garment Template",
    )

    measurement_date = fields.Date(string="Measurement Date")
    mrp_id = fields.Many2one("mrp.production", string="Manufacturing Order")

    length = fields.Float(string="Length")
    shoulder = fields.Float(string="Shoulder")
    sleeve_length = fields.Float(string="Sleeve Length")
    chest = fields.Float(string="Chest")
    waist = fields.Float(string="Waist")
    hip = fields.Float(string="Hip")
    neck = fields.Float(string="Neck")
    bottom_width = fields.Float(string="Bottom Width")

    fabric_preference = fields.Char(string="Fabric Preference")
    style_preference = fields.Text(string="Style Preference")
    fitting_style = fields.Char(string="Fitting Style")
    measurement_notes = fields.Text(string="Measurement Notes")

    display_name = fields.Char(compute="_compute_display_name", store=True)

    front_design = fields.Selection(
        [("plain", "Plain"), ("design1", "Design Option 1"), ("design2", "Design Option 2")])
    sleeve_style = fields.Selection([("normal", "Normal"), ("other", "Other")])
    collar_style = fields.Selection(
        [("P1", "P1"), ("P2", "P2"), ("P3", "P3"), ("P4", "P4"), ("P5", "P5"), ("P6", "P6")])
    cuff_style = fields.Selection([("A", "A"), ("B", "B"), ("C", "C"), ("D", "D"), ("E", "E")])
    buttons_type = fields.Selection([("normal", "Normal"), ("tich", "Tich"), ("zipper", "Zipper")])
    stitching_type = fields.Selection([("normal", "Normal"), ("edge", "Edge")])

    pocket_pen_big = fields.Boolean(string="Pen Pocket (Big)")
    pocket_pen_small = fields.Boolean(string="Pen Pocket (Small)")
    pocket_front = fields.Boolean(string="Front Pocket")
    pocket_key_left = fields.Boolean(string="Key Pocket (Left)")
    pocket_key_right = fields.Boolean(string="Key Pocket (Right)")

    @api.depends("partner_id", "measurement_date", "garment_template")
    def _compute_display_name(self):
        for rec in self:
            customer = rec.partner_id.name or "Customer"
            date = rec.measurement_date or "No Date"
            template = dict(self._fields["garment_template"].selection).get(rec.garment_template, "No Template")
            rec.display_name = f"{customer} - {template} - {date}"

    @api.onchange("partner_id", "garment_template")
    def _onchange_partner_autofill(self):
        for rec in self:
            if not rec.partner_id:
                return

            domain = [("partner_id", "=", rec.partner_id.id)]

            last = False
            if rec.garment_template:
                last = self.search(
                    domain + [("garment_template", "=", rec.garment_template)],
                    order="create_date desc, id desc",
                    limit=1
                )

            if not last:
                last = self.search(domain, order="create_date desc, id desc", limit=1)

            if not last:
                return

            rec.length = last.length
            rec.shoulder = last.shoulder
            rec.sleeve_length = last.sleeve_length
            rec.chest = last.chest
            rec.waist = last.waist
            rec.hip = last.hip
            rec.neck = last.neck
            rec.bottom_width = last.bottom_width

            rec.fabric_preference = last.fabric_preference
            rec.style_preference = last.style_preference
            rec.fitting_style = last.fitting_style
            rec.measurement_notes = last.measurement_notes


# -------------------- Customer Documents / Folder / Tag --------------------
class CustomerDocuments(models.Model):
    _name = "customer.documents"
    _description = "Customer Documents"
    _inherit = ["mail.thread", "mail.activity.mixin", "portal.mixin"]

    name = fields.Char(string="Document Name", required=True, translate=True)


    file = fields.Binary(string="File", attachment=True, required=False)
    filename = fields.Char(string="File Name")

    attachment_ids = fields.Many2many(
        "ir.attachment",
        "customer_documents_ir_attachment_rel",
        "document_id",
        "attachment_id",
        string="Files",
        help="Upload multiple files for the same document record.",
    )

    document_type = fields.Selection(
        [
            ("measurement", "Measurement"),
            ("invoice", "Invoice"),
            ("contract", "Contract"),
            ("design", "Design / Reference"),
            ("accessories", "Accessories / Extras"),
            ("other", "Other"),
        ],
        string="Document Type",
        default="other",
    )

    upload_date = fields.Datetime(string="Upload Date", default=fields.Datetime.now)
    partner_id = fields.Many2one("res.partner", string="Customer", required=True)
    tailor_order_id = fields.Many2one("tailor.order", string="Tailor Order")

    folder_id = fields.Many2one("customer.document.folder", string="Folder")
    tag_ids = fields.Many2many(
        "customer.document.tag",
        "customer_document_tag_rel",
        "document_id",
        "tag_id",
        string="Tags",
        default=lambda self: self.env["customer.document.tag"],
    )

    uploaded_by = fields.Many2one("res.users", string="Uploaded By", default=lambda self: self.env.user)
    description = fields.Text(string="Description")

    is_required = fields.Boolean(string="Required", default=True)
    is_missing = fields.Boolean(string="Missing", compute="_compute_is_missing", store=True)

    @api.depends("file", "attachment_ids", "is_required")
    def _compute_is_missing(self):
        for rec in self:
            has_any_file = bool(rec.file) or bool(rec.attachment_ids)
            rec.is_missing = bool(rec.is_required) and not has_any_file

    def _schedule_document_activity(self, users, summary, note):
        activity_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        if not activity_type:
            return

        Activity = self.env["mail.activity"].sudo()

        for doc in self:
            for user in users:
                exists = Activity.search_count([
                    ("res_model", "=", doc._name),
                    ("res_id", "=", doc.id),
                    ("user_id", "=", user.id),
                    ("activity_type_id", "=", activity_type.id),
                    ("summary", "=", summary),
                    ("date_done", "=", False),
                ])
                if exists:
                    continue

                doc.activity_schedule(
                    activity_type_id=activity_type.id,
                    user_id=user.id,
                    summary=summary,
                    note=note,
                    date_deadline=fields.Date.today(),
                )

    def _ensure_binary_file_is_attachment(self):
        Attachment = self.env["ir.attachment"].sudo()
        for rec in self:
            if not rec.file:
                continue

            filename = (rec.filename or rec.name or "Document").strip() or "Document"
            mimetype = mimetypes.guess_type(filename)[0] or "application/octet-stream"

            existing = rec.attachment_ids.filtered(lambda a: a.name == filename and a.datas == rec.file)
            if existing:
                continue

            att = Attachment.create({
                "name": filename,
                "datas": rec.file,
                "res_model": rec._name,
                "res_id": rec.id,
                "mimetype": mimetype,
            })

            rec.sudo().write({"attachment_ids": [(4, att.id)]})

    def _is_admin(self):
        return (
                self.env.user.has_group("tailor_management.group_tailor_admin")
                or self.env.user.has_group("base.group_system")
        )

    def _m2m_removes_existing(self, rec, commands):
        if not commands:
            return False

        existing = set(rec.attachment_ids.ids)

        for cmd in commands:
            if not isinstance(cmd, (list, tuple)) or not cmd:
                continue

            op = cmd[0]

            if op == 3 and len(cmd) > 1 and cmd[1] in existing:
                return True
            if op == 2 and len(cmd) > 1 and cmd[1] in existing:
                return True
            if op == 5 and existing:
                return True
            if op == 6 and len(cmd) > 2:
                new_ids = set(cmd[2] or [])
                if not existing.issubset(new_ids):
                    return True

        return False

    def write(self, vals):
        if not self._is_admin():
            if "file" in vals and not vals.get("file"):
                for rec in self:
                    if rec.file:
                        raise UserError(_("Only Admin/Managers can delete/remove document files."))

            if "attachment_ids" in vals:
                commands = vals.get("attachment_ids") or []
                for rec in self:
                    if self._m2m_removes_existing(rec, commands):
                        raise UserError(_("Only Admin/Managers can delete/remove document files."))

        res = super(CustomerDocuments, self).write(vals)

        if "file" in vals and vals.get("file"):
            self._ensure_binary_file_is_attachment()

        return res

    @api.model_create_multi
    def create(self, vals_list):
        fixed_vals_list = []
        for vals in vals_list:
            vals = dict(vals)

            if not vals.get("tailor_order_id") and self.env.context.get("default_tailor_order_id"):
                vals["tailor_order_id"] = self.env.context.get("default_tailor_order_id")

            if not vals.get("partner_id") and self.env.context.get("default_partner_id"):
                dp = self.env.context.get("default_partner_id")
                vals["partner_id"] = dp[0] if isinstance(dp, (list, tuple)) else dp

            if not vals.get("partner_id") and vals.get("tailor_order_id"):
                order = self.env["tailor.order"].browse(vals["tailor_order_id"])
                if order and order.partner_id:
                    vals["partner_id"] = order.partner_id.id

            fixed_vals_list.append(vals)

        records = super(CustomerDocuments, self).create(fixed_vals_list)

        mt_note = self.env.ref("mail.mt_note", raise_if_not_found=False)

        for rec in records:
            if rec.file:
                rec._ensure_binary_file_is_attachment()

            partner_ids = set()
            if rec.partner_id:
                partner_ids.add(rec.partner_id.id)

            if rec.tailor_order_id and rec.tailor_order_id.tailor_id and rec.tailor_order_id.tailor_id.partner_id:
                partner_ids.add(rec.tailor_order_id.tailor_id.partner_id.id)

            if self.env.user.partner_id:
                partner_ids.add(self.env.user.partner_id.id)

            if partner_ids:
                rec.message_subscribe(list(partner_ids))

            if rec.tailor_order_id:
                rec.tailor_order_id.message_post(
                    body=f"<b>Document Record Created</b>: {rec.name} ({rec.document_type})",
                    message_type="comment",
                    subtype_id=mt_note.id if mt_note else False,
                )

        return records

    def action_download_file(self):
        self.ensure_one()

        if self.attachment_ids:
            att = self.attachment_ids.sorted(lambda a: (a.create_date or fields.Datetime.now(), a.id))[-1]
            return {
                "type": "ir.actions.act_url",
                "url": f"/web/content/{att.id}?download=true",
                "target": "new",
            }

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{self._name}/{self.id}/file/{self.filename}?download=true",
            "target": "new",
        }


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    def _is_tailor_admin_or_system(self):
        return (
                self.env.user.has_group("tailor_management.group_tailor_admin")
                or self.env.user.has_group("base.group_system")
        )

    def write(self, vals):
        docs_atts = self.filtered(lambda a: a.res_model == "customer.documents" and a.res_id)

        if docs_atts and not self._is_tailor_admin_or_system():
            if any(k in vals for k in ("res_model", "res_id")):
                new_model = vals.get("res_model", None)
                new_id = vals.get("res_id", None)

                if (new_model is False) or (new_id is False) or (new_model and new_model != "customer.documents"):
                    raise UserError(_("Only Admin/Managers can remove document files."))

                if (new_model in (None, "customer.documents")) and (new_id not in (None, False)):
                    for att in docs_atts:
                        if new_id != att.res_id:
                            raise UserError(_("Only Admin/Managers can move/remove document files."))

        return super().write(vals)

    def unlink(self):
        docs_atts = self.filtered(lambda a: a.res_model == "customer.documents")
        if docs_atts and not self._is_tailor_admin_or_system():
            raise UserError(_("Only Admin/Managers can delete files from documents."))
        return super().unlink()


class CustomerDocumentFolder(models.Model):
    _name = "customer.document.folder"
    _description = "Document Folder"

    name = fields.Char(string="Folder Name", required=True)
    description = fields.Text(string="Description")
    active = fields.Boolean(string="Active", default=True)
    document_ids = fields.One2many("customer.documents", "folder_id", string="Documents")


class CustomerDocumentTag(models.Model):
    _name = "customer.document.tag"
    _description = "Document Tag"

    name = fields.Char(string="Tag Name", required=True)
    document_ids = fields.Many2many(
        "customer.documents",
        "customer_document_tag_rel",
        "tag_id",
        "document_id",
        string="Documents",
    )


class StockMove(models.Model):
    _inherit = "stock.move"
    tailor_order_id = fields.Many2one("tailor.order", string="Tailor Order")
