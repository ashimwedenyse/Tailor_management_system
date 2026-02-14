from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

# -------------------- Customer Measurements --------------------
class CustomerMeasurements(models.Model):
    _name = 'customer.measurements'
    _description = 'Customer Tailor Measurements'
    _rec_name = 'display_name'

    partner_id = fields.Many2one('res.partner', string='Customer', required=True)
    sale_order_id = fields.Many2one('sale.order', string="Sale Order")  # optional link to a Sale Order
    measurement_date = fields.Date(string="Measurement Date")
    mrp_id = fields.Many2one('mrp.production', string="Manufacturing Order")

    # Body measurements
    length = fields.Float(string="Length")
    shoulder = fields.Float(string="Shoulder")
    sleeve_length = fields.Float(string="Sleeve Length")
    chest = fields.Float(string="Chest")
    waist = fields.Float(string="Waist")
    hip = fields.Float(string="Hip")
    neck = fields.Float(string="Neck")
    bottom_width = fields.Float(string="Bottom Width")

    # Preferences
    fabric_preference = fields.Char(string="Fabric Preference")
    style_preference = fields.Text(string="Style Preference")
    fitting_style = fields.Char(string="Fitting Style")
    measurement_notes = fields.Text(string="Measurement Notes")

    # -------------------- AI metadata (optional) --------------------
    measured_by_ai = fields.Boolean(string="Measured by AI", default=False, readonly=True)
    ai_method = fields.Selection(
        [
            ('pose_2d', '2D Pose (front + side)'),
            ('depth', 'Depth / LiDAR'),
            ('manual', 'Manual'),
        ],
        string='AI Method',
        default='manual',
        readonly=True,
    )
    ai_confidence = fields.Float(string='AI Confidence (%)', readonly=True)
    ai_raw_json = fields.Text(string='AI Raw Result (JSON)', readonly=True)

    # Computed name for display
    display_name = fields.Char(compute="_compute_display_name", store=True)

    @api.depends('partner_id', 'measurement_date')
    def _compute_display_name(self):
        for rec in self:
            customer = rec.partner_id.name or "Customer"
            date = rec.measurement_date or "No Date"
            rec.display_name = f"{customer} - {date}"

