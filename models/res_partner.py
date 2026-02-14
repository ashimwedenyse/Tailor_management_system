from odoo import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    measurements_ids = fields.One2many(
        'customer.measurements',
        'partner_id',
        string='Tailor Measurements',
    )

    def action_open_ai_measure_wizard(self):
        """Open the AI measurement wizard for this customer."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'AI Measurements',
            'res_model': 'tailor.ai.measure.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_target_model': 'res.partner',
                'default_partner_id': self.id,
            },
        }
