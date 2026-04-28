import json
import logging
import re

from odoo import models
from odoo.exceptions import UserError

from .ai_providers import GeminiProvider, OpenRouterProvider

_logger = logging.getLogger(__name__)


class EstateAiService(models.AbstractModel):
    _name = 'estate.ai.service'
    _description = 'Estate AI Service'
    _SUPPORTED_PROVIDERS = ('openrouter', 'gemini')

    def recommend_offer(self, property_record):
        property_record.ensure_one()
        offers = property_record.offer_ids.filtered(lambda offer: offer.state in ('pending', 'accepted'))
        if not offers:
            raise UserError('No pending/accepted offers available for AI recommendation.')

        prompt = self._build_prompt(property_record, offers)
        provider = self._get_provider()
        try:
            response_text = self._call_provider(provider, prompt)
        except Exception as exception:
            _logger.warning('Estate AI fallback triggered for property %s: %s', property_record.id, exception)
            return self._fallback_recommendation(offers, str(exception), provider)

        parsed = self._parse_response_json(response_text)
        if not parsed:
            return self._fallback_recommendation(offers, 'AI response format was invalid.', provider)

        recommended_offer = offers.filtered(lambda offer: offer.id == parsed.get('offer_id'))[:1]
        if not recommended_offer:
            return self._fallback_recommendation(offers, 'AI selected an unknown offer.', provider)

        return {
            'offer': recommended_offer,
            'reasoning': parsed.get('reasoning') or 'AI recommendation completed.',
            'confidence': self._normalize_confidence(parsed.get('confidence')),
            'provider': provider,
        }

    def _call_provider(self, provider, prompt):
        handlers = {
            'openrouter': self._call_openrouter,
            'gemini': self._call_gemini,
        }
        return handlers[provider](prompt)

    def _get_provider(self):
        provider = self._get_config('estate.ai_provider', 'openrouter')
        return provider if provider in self._SUPPORTED_PROVIDERS else 'openrouter'

    def _get_config(self, key, default=None):
        return self.env['ir.config_parameter'].sudo().get_param(key) or default

    def _build_prompt(self, property_record, offers):
        offer_lines = []
        for offer in offers:
            offer_lines.append(
                f"- offer_id={offer.id}, price={offer.price}, state={offer.state}, partner={offer.partner_id.display_name}, deadline={offer.deadline or 'N/A'}"
            )
        return f"""
You are an assistant helping a real estate manager choose the best offer.
Return only valid JSON with this exact schema:
{{
  "offer_id": <integer>,
  "reasoning": "<short explanation>",
  "confidence": <number from 0 to 100>
}}

Decision policy:
- Prioritize highest safe price.
- Prefer pending offers over already accepted ones.
- Consider deadline urgency and buyer credibility inferred from available info.

Property:
- id: {property_record.id}
- title: {property_record.name}
- expected_price: {property_record.expected_price}
- best_price: {property_record.best_price}
- state: {property_record.state}

Offers:
{chr(10).join(offer_lines)}
""".strip()

    def _call_openrouter(self, prompt):
        return OpenRouterProvider(self._get_config).generate(prompt)

    def _call_gemini(self, prompt):
        return GeminiProvider(self._get_config).generate(prompt)

    def _parse_response_json(self, response_text):
        if not response_text:
            return None
        cleaned = response_text.strip()
        cleaned = re.sub(r'^```json\s*|\s*```$', '', cleaned, flags=re.IGNORECASE | re.MULTILINE).strip()
        cleaned = self._extract_first_json_object(cleaned)
        try:
            return json.loads(cleaned)
        except Exception:
            return None

    def _extract_first_json_object(self, text):
        start_index = text.find('{')
        if start_index < 0:
            return text
        depth = 0
        in_string = False
        escaped = False
        for index in range(start_index, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == '\\':
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
                continue
            if char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    return text[start_index:index + 1]
        return text

    def _normalize_confidence(self, value):
        try:
            return max(0.0, min(100.0, float(value)))
        except Exception:
            return 0.0

    def _fallback_recommendation(self, offers, reason, provider):
        best_offer = offers.sorted(key=lambda offer: offer.price, reverse=True)[:1]
        return {
            'offer': best_offer,
            'reasoning': f'Fallback recommendation used: {self._normalize_reason(reason, provider)}',
            'confidence': 50.0,
            'provider': 'fallback',
        }

    def _normalize_reason(self, reason, provider):
        lower_reason = (reason or '').lower()
        if '429' in lower_reason or 'quota' in lower_reason or 'rate limit' in lower_reason:
            return f'{provider.title()} quota exceeded. Using rule-based recommendation.'
        if 'invalid' in lower_reason or 'unauthorized' in lower_reason:
            return f'{provider.title()} API key is invalid/unauthorized. Using rule-based recommendation.'
        if 'model not found' in lower_reason:
            return f'{provider.title()} model not found in Settings. Using rule-based recommendation.'
        return f'{provider.title()} unavailable. Using rule-based recommendation.'
