from unittest.mock import patch

from odoo.tests.common import TransactionCase


class TestEstateAiService(TransactionCase):
    def setUp(self):
        super().setUp()
        self.ai_service = self.env['estate.ai.service']

    def test_parse_response_json_extracts_first_object(self):
        payload = 'prefix text ```json {"offer_id": 11, "reasoning": "ok", "confidence": 120} ``` suffix'
        parsed = self.ai_service._parse_response_json(payload)
        self.assertEqual(parsed['offer_id'], 11)
        self.assertEqual(parsed['reasoning'], 'ok')

    def test_normalize_confidence_clamps_value(self):
        self.assertEqual(self.ai_service._normalize_confidence(150), 100.0)
        self.assertEqual(self.ai_service._normalize_confidence(-5), 0.0)
        self.assertEqual(self.ai_service._normalize_confidence('abc'), 0.0)

    def test_get_provider_falls_back_when_invalid(self):
        self.env['ir.config_parameter'].sudo().set_param('estate.ai_provider', 'unknown_provider')
        self.assertEqual(self.ai_service._get_provider(), 'openrouter')

    def test_generate_property_description_parses_description_json(self):
        prop = self.env['estate.property'].create({'name': 'Test Home', 'expected_price': 100000})
        response = '{"description": "A beautiful, market-ready home."}'
        with patch(
            'odoo.addons.estate.models.ai_service.EstateAiService._call_openrouter',
            return_value=response,
        ):
            result = self.ai_service.generate_property_description(prop, style='family', language='en', rules='Avoid exaggeration.')
        self.assertEqual(result['description'], 'A beautiful, market-ready home.')
        self.assertEqual(result['provider'], 'openrouter')

    def test_call_provider_passes_expect_json_flag(self):
        with patch(
            'odoo.addons.estate.models.ai_providers.OpenRouterProvider.generate',
            return_value='{"ok":true}',
        ) as mocked:
            self.ai_service._call_provider('openrouter', 'x', expect_json=True)
        self.assertTrue(mocked.called)
        self.assertTrue(mocked.call_args.kwargs.get('json_mode'))
