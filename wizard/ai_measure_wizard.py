# -*- coding: utf-8 -*-
import base64
import json
import logging
import urllib.request
import urllib.error

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def _post_json(url, payload, headers=None, timeout=30):
    """Small HTTP helper without external deps."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url=url,
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")
        except Exception:
            pass
        raise UserError(_("AI service error (%s): %s") % (e.code, body or e.reason))
    except Exception as e:
        raise UserError(_("Could not reach AI service: %s") % (e,))


class TailorAIMeasureWizard(models.TransientModel):
    _name = "tailor.ai.measure.wizard"
    _description = "AI Measurement Wizard"

    target_model = fields.Selection(
        [('res.partner', 'Customer'), ('tailor.order', 'Tailor Order')],
        string="Target",
        required=True,
        default='res.partner',
    )
    partner_id = fields.Many2one('res.partner', string="Customer")
    tailor_order_id = fields.Many2one('tailor.order', string="Tailor Order")

    # Capture inputs (upload from phone/web; mobile browsers can open camera for file input)
    front_image = fields.Binary(string="Front Photo", required=True)
    front_filename = fields.Char(string="Front Filename")
    side_image = fields.Binary(string="Side Photo", required=True)
    side_filename = fields.Char(string="Side Filename")

    reference_type = fields.Selection(
        [('a4', 'A4 Paper'), ('card', 'Credit Card'), ('none', 'No Reference (lower accuracy)')],
        string="Reference Object",
        default='a4',
        required=True,
    )
    height_cm = fields.Float(string="Known Height (cm)", help="Optional. Improves scaling if you don't use a reference object.")

    store_images = fields.Boolean(
        string="Store Images on Customer (Attachment)",
        default=False,
        help="If enabled, the uploaded images are stored as attachments on the target record. If disabled, only the measurements are stored.",
    )

    result_json = fields.Text(string="Raw AI Result (JSON)", readonly=True)
    confidence = fields.Float(string="Confidence (%)", readonly=True)

    # Suggested measurement outputs (cm)
    length = fields.Float(string="Length (cm)", readonly=True)
    shoulder = fields.Float(string="Shoulder (cm)", readonly=True)
    sleeve_length = fields.Float(string="Sleeve Length (cm)", readonly=True)
    chest = fields.Float(string="Chest (cm)", readonly=True)
    waist = fields.Float(string="Waist (cm)", readonly=True)
    hip = fields.Float(string="Hip (cm)", readonly=True)
    neck = fields.Float(string="Neck (cm)", readonly=True)
    bottom_width = fields.Float(string="Bottom Width (cm)", readonly=True)

    def _get_target_record(self):
        self.ensure_one()
        if self.target_model == 'res.partner':
            if not self.partner_id:
                raise UserError(_("Please select a customer."))
            return self.partner_id
        if self.target_model == 'tailor.order':
            if not self.tailor_order_id:
                raise UserError(_("Please select a tailor order."))
            return self.tailor_order_id
        raise UserError(_("Unsupported target."))

    def action_compute(self):
        """Call AI service, show preview results in wizard."""
        self.ensure_one()
        url = (self.env['ir.config_parameter'].sudo().get_param('tailor_management.ai_service_url') or '').rstrip('/')
        token = self.env['ir.config_parameter'].sudo().get_param('tailor_management.ai_service_token') or ''
        if not url:
            raise UserError(_("AI Service URL is not configured. Go to Settings → General Settings → Tailor AI."))

        payload = {
            'front_image_b64': (self.front_image or b'').decode('utf-8') if isinstance(self.front_image, (bytes, bytearray)) else (self.front_image or ''),
            'side_image_b64': (self.side_image or b'').decode('utf-8') if isinstance(self.side_image, (bytes, bytearray)) else (self.side_image or ''),
            'reference_type': self.reference_type,
            'height_cm': self.height_cm or None,
        }
        headers = {}
        if token:
            headers['Authorization'] = f"Bearer {token}"

        resp = _post_json(f"{url}/v1/measurements/from_images", payload, headers=headers, timeout=60)

        # Expected response keys
        meas = resp.get('measurements') or {}
        confidence = float(resp.get('confidence', 0.0) or 0.0)
        self.write({
            'result_json': json.dumps(resp, indent=2, ensure_ascii=False),
            'confidence': confidence,
            'length': float(meas.get('length', 0.0) or 0.0),
            'shoulder': float(meas.get('shoulder', 0.0) or 0.0),
            'sleeve_length': float(meas.get('sleeve_length', 0.0) or 0.0),
            'chest': float(meas.get('chest', 0.0) or 0.0),
            'waist': float(meas.get('waist', 0.0) or 0.0),
            'hip': float(meas.get('hip', 0.0) or 0.0),
            'neck': float(meas.get('neck', 0.0) or 0.0),
            'bottom_width': float(meas.get('bottom_width', 0.0) or 0.0),
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_apply(self):
        """Write results into target records."""
        self.ensure_one()
        target = self._get_target_record()

        # Save images as attachments (optional)
        if self.store_images:
            self.env['ir.attachment'].sudo().create([
                {
                    'name': self.front_filename or 'front.jpg',
                    'res_model': target._name,
                    'res_id': target.id,
                    'type': 'binary',
                    'datas': self.front_image,
                    'mimetype': 'image/jpeg',
                },
                {
                    'name': self.side_filename or 'side.jpg',
                    'res_model': target._name,
                    'res_id': target.id,
                    'type': 'binary',
                    'datas': self.side_image,
                    'mimetype': 'image/jpeg',
                },
            ])

        # Apply to Tailor Order fields
        if target._name == 'tailor.order':
            target.write({
                'length': self.length,
                'shoulder': self.shoulder,
                'sleeve_length': self.sleeve_length,
                'chest': self.chest,
                'waist': self.waist,
                'hip': self.hip,
                'neck': self.neck,
                'bottom_width': self.bottom_width,
            })

        # Always create a measurement record under the customer if we have one
        partner = self.partner_id
        if target._name == 'tailor.order' and target.partner_id:
            partner = target.partner_id

        if partner:
            self.env['customer.measurements'].sudo().create({
                'partner_id': partner.id,
                'measurement_date': fields.Date.context_today(self),
                'sale_order_id': False,
                'mrp_id': False,
                'length': self.length,
                'shoulder': self.shoulder,
                'sleeve_length': self.sleeve_length,
                'chest': self.chest,
                'waist': self.waist,
                'hip': self.hip,
                'neck': self.neck,
                'bottom_width': self.bottom_width,
                'measured_by_ai': True,
                'ai_method': 'pose_2d',
                'ai_confidence': self.confidence,
                'ai_raw_json': self.result_json,
            })

        return {'type': 'ir.actions.act_window_close'}
