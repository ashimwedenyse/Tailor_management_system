# -*- coding: utf-8 -*-
from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    tailor_ai_service_url = fields.Char(
        string="Tailor AI Service URL",
        config_parameter="tailor_management.tailor_ai_service_url",
        help="Base URL of your AI service (example: http://127.0.0.1:8008).",
    )

    tailor_ai_token = fields.Char(
        string="Tailor AI Token",
        config_parameter="tailor_management.tailor_ai_token",
        help="Token/API key used to authenticate with the AI service.",
    )
