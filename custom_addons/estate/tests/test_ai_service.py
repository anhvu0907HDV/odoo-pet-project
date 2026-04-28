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
