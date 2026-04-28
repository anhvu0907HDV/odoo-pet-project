from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    estate_ai_provider = fields.Selection(
        selection=[('openrouter', 'OpenRouter'), ('gemini', 'Gemini')],
        string='Estate AI Provider',
        config_parameter='estate.ai_provider',
        default='openrouter',
    )
    estate_openrouter_model = fields.Char(
        string='Estate OpenRouter Model',
        config_parameter='estate.openrouter_model',
        default='openrouter/free',
        help='OpenRouter model id (example: openrouter/free).',
    )
    estate_openrouter_api_key = fields.Char(
        string='Estate OpenRouter API Key',
        config_parameter='estate.openrouter_api_key',
        help='API key used for OpenRouter offer recommendation.',
    )
    estate_gemini_model = fields.Char(
        string='Estate Gemini Model',
        config_parameter='estate.gemini_model',
        default='gemini-2.0-flash',
        help='Model name for Gemini generateContent API (example: gemini-2.0-flash).',
    )
    estate_gemini_api_key = fields.Char(
        string='Estate Gemini API Key',
        config_parameter='estate.gemini_api_key',
        help='API key used for AI offer recommendation.',
    )
