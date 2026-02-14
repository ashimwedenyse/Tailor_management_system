from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ai_service_url = fields.Char(
        string='AI Service URL',
        config_parameter='tailor_management.ai_service_url',
        default='http://127.0.0.1:8008',
        help='Base URL of the Tailor AI microservice (FastAPI). Example: http://127.0.0.1:8008',
    )

    ai_service_token = fields.Char(
        string='AI Service Token',
        config_parameter='tailor_management.ai_service_token',
        default='change-me',
        help='Shared token used by Odoo when calling the AI service.',
    )
