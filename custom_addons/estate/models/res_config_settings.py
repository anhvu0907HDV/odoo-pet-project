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

    estate_ollama_base_url = fields.Char(
        string='Estate Ollama Base URL',
        config_parameter='estate.ollama_base_url',
        default='http://localhost:11434',
        help='Base URL for Ollama server (example: http://localhost:11434).',
    )
    estate_ollama_model = fields.Char(
        string='Estate Ollama Model',
        config_parameter='estate.ollama_model',
        default='mistral',
        help='Model name used for generation (example: mistral).',
    )
    estate_ollama_embed_model = fields.Char(
        string='Estate Ollama Embedding Model',
        config_parameter='estate.ollama_embed_model',
        default='nomic-embed-text',
        help='Embedding model name (example: nomic-embed-text).',
    )
    estate_embedding_provider = fields.Selection(
        selection=[('ollama', 'Ollama')],
        string='Estate Embedding Provider',
        config_parameter='estate.embedding_provider',
        default='ollama',
        help='Provider used to generate embeddings for RAG.',
    )
