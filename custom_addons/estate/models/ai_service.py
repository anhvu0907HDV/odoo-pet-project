import json
import logging
import re
from urllib import error, request

from odoo import models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class EstateAiService(models.AbstractModel):
    _name = 'estate.ai.service'
    _description = 'Estate AI Service'

    def recommend_offer(self, property_record):
        property_record.ensure_one()
        offers = property_record.offer_ids.filtered(lambda offer: offer.state in ('pending', 'accepted'))
        if not offers:
            raise UserError('No pending/accepted offers available for AI recommendation.')

        prompt = self._build_prompt(property_record, offers)
        provider = self._get_provider()
        try:
            if provider == 'openrouter':
                response_text = self._call_openrouter(prompt)
            else:
                response_text = self._call_gemini(prompt)
        except Exception as error_message:
            _logger.warning('Estate AI fallback triggered for property %s: %s', property_record.id, error_message)
            return self._fallback_recommendation(property_record, offers, str(error_message), provider)

        parsed = self._parse_response_json(response_text)
        if not parsed:
            return self._fallback_recommendation(property_record, offers, 'AI response format was invalid.', provider)

        recommended_offer = offers.filtered(lambda offer: offer.id == parsed.get('offer_id'))[:1]
        if not recommended_offer:
            return self._fallback_recommendation(property_record, offers, 'AI selected an unknown offer.', provider)

        return {
            'offer': recommended_offer,
            'reasoning': parsed.get('reasoning') or 'AI recommendation completed.',
            'confidence': self._normalize_confidence(parsed.get('confidence')),
            'provider': provider,
        }

    def _get_provider(self):
        provider = self.env['ir.config_parameter'].sudo().get_param('estate.ai_provider') or 'openrouter'
        return provider if provider in ('openrouter', 'gemini') else 'openrouter'

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
        api_key = self.env['ir.config_parameter'].sudo().get_param('estate.openrouter_api_key')
        if not api_key:
            raise RuntimeError('OpenRouter API key is missing.')
        model = self.env['ir.config_parameter'].sudo().get_param('estate.openrouter_model') or 'openrouter/free'
        payload = {
            'model': model,
            'messages': [{'role': 'user', 'content': prompt}],
            'temperature': 0.1,
            'response_format': {'type': 'json_object'},
        }
        req = request.Request(
            'https://openrouter.ai/api/v1/chat/completions',
            data=json.dumps(payload).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
            },
            method='POST',
        )
        try:
            with request.urlopen(req, timeout=25) as response:
                body = json.loads(response.read().decode('utf-8'))
                return body.get('choices', [{}])[0].get('message', {}).get('content', '')
        except error.HTTPError as http_error:
            raw_body = http_error.read().decode('utf-8', errors='ignore')
            if http_error.code == 429:
                raise RuntimeError('OpenRouter quota/rate limit exceeded (HTTP 429).') from http_error
            if http_error.code in (401, 403):
                raise RuntimeError('OpenRouter API key is invalid or unauthorized.') from http_error
            raise RuntimeError(f'OpenRouter request failed ({http_error.code}): {raw_body[:180]}') from http_error

    def _call_gemini(self, prompt):
        api_key = (
            self.env['ir.config_parameter'].sudo().get_param('estate.gemini_api_key')
            or self.env['ir.config_parameter'].sudo().get_param('gemini_api_key')
        )
        if not api_key:
            raise RuntimeError('Gemini API key is missing.')
        model_name = self.env['ir.config_parameter'].sudo().get_param('estate.gemini_model') or 'gemini-2.0-flash'
        endpoints = [
            f'https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent',
            f'https://generativelanguage.googleapis.com/v1/models/{model_name}:generateContent',
        ]
        payload = {
            'contents': [{'parts': [{'text': prompt}]}],
            'generationConfig': {'temperature': 0.1},
        }
        http_codes = []
        details = []
        for endpoint in endpoints:
            req = request.Request(
                f'{endpoint}?key={api_key}',
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            try:
                with request.urlopen(req, timeout=20) as response:
                    body = json.loads(response.read().decode('utf-8'))
                    return (
                        body.get('candidates', [{}])[0]
                        .get('content', {})
                        .get('parts', [{}])[0]
                        .get('text', '')
                    )
            except error.HTTPError as http_error:
                raw_body = http_error.read().decode('utf-8', errors='ignore')
                http_codes.append(http_error.code)
                details.append(f'{endpoint} -> {http_error.code} {raw_body[:140]}')
            except Exception as exception:
                details.append(f'{endpoint} -> {exception}')
        if 429 in http_codes:
            raise RuntimeError('Gemini quota exceeded (HTTP 429).')
        if 401 in http_codes or 403 in http_codes:
            raise RuntimeError('Gemini API key is invalid or unauthorized.')
        if 404 in http_codes:
            raise RuntimeError('Gemini model not found. Check Gemini Model setting.')
        raise RuntimeError(f'Gemini request failed. {" | ".join(details)}')

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

    def _fallback_recommendation(self, property_record, offers, reason, provider):
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
