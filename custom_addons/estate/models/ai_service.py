import json
import logging
import re

from odoo import api, models
from odoo.exceptions import UserError

from .ai_providers import GeminiProvider, OllamaProvider, OpenRouterProvider

_logger = logging.getLogger(__name__)


class EstateAiService(models.AbstractModel):
    _name = 'estate.ai.service'
    _description = 'Estate AI Service'
    _SUPPORTED_PROVIDERS = ('openrouter', 'gemini', 'ollama')

    def recommend_offer(self, property_record):
        property_record.ensure_one()
        offers = property_record.offer_ids.filtered(lambda offer: offer.state in ('pending', 'accepted'))
        if not offers:
            raise UserError('No pending/accepted offers available for AI recommendation.')

        prompt = self._build_prompt(property_record, offers)
        provider = self._get_provider()
        try:
            response_text = self._call_provider(provider, prompt, expect_json=True)
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

    def generate_property_description(self, property_record, *, style=None, language=None, rules=None):
        property_record.ensure_one()
        provider = self._get_provider()
        style = (style or 'luxury').strip() or 'luxury'
        language = (language or 'en').strip() or 'en'
        rules = (rules or '').strip()

        prompt = self._build_description_prompt(property_record, style=style, language=language, rules=rules)
        try:
            response_text = self._call_provider(provider, prompt, expect_json=True)
        except Exception as exception:
            _logger.warning(
                'Estate AI description fallback triggered for property %s: %s',
                property_record.id,
                exception,
            )
            return self._fallback_description(property_record, str(exception), provider, style, language)

        parsed = self._parse_response_json(response_text)
        description = (parsed or {}).get('description') if isinstance(parsed, dict) else None
        description = (description or '').strip()
        if not description:
            return self._fallback_description(property_record, 'AI response format was invalid.', provider, style, language)

        return {
            'description': description,
            'provider': provider,
            'style': style,
            'language': language,
        }

    @api.model
    def preview_property_description(self, values):
        style = (values or {}).get('style') or 'luxury'
        language = (values or {}).get('language') or 'en'
        rules = (values or {}).get('rules') or ''

        payload = self._normalize_property_payload(values or {})
        missing_required = payload['missing_required']
        if missing_required:
            raise UserError('Missing required fields: %s' % ', '.join(missing_required))

        provider = self._get_provider()
        prompt = self._build_description_prompt_from_payload(payload, style=style, language=language, rules=rules)
        try:
            response_text = self._call_provider(provider, prompt, expect_json=True)
        except Exception as exception:
            _logger.warning('Estate AI preview description fallback: %s', exception)
            return self._fallback_description_from_payload(payload, str(exception), provider, style, language)

        parsed = self._parse_response_json(response_text)
        description = (parsed or {}).get('description') if isinstance(parsed, dict) else None
        description = (description or '').strip()
        if not description:
            return self._fallback_description_from_payload(payload, 'AI response format was invalid.', provider, style, language)

        return {
            'description': description,
            'provider': provider,
            'style': style,
            'language': language,
        }

    def _call_provider(self, provider, prompt, *, expect_json=False):
        handlers = {
            'openrouter': self._call_openrouter,
            'gemini': self._call_gemini,
            'ollama': self._call_ollama,
        }
        return handlers[provider](prompt, expect_json=expect_json)

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

    def _build_description_prompt(self, property_record, *, style, language, rules):
        tag_names = ', '.join(property_record.tag_ids.mapped('name')) if property_record.tag_ids else ''
        property_type = property_record.property_type_id.name if property_record.property_type_id else ''
        rules_block = f"\nAdditional rules from the user:\n{rules}\n" if rules else ""
        return f"""
You are a professional real estate marketing expert.

You MUST return ONLY a single valid JSON object (no markdown, no code fences, no extra keys, no extra text) with exactly this schema:
{{
  "description": "<string>"
}}

Write a high-quality property description based on:

Property:
- title: {property_record.name or ''}
- property_type: {property_type}
- price: {property_record.expected_price}
- bedrooms: {property_record.bedrooms or 0}
- living_area: {property_record.living_area or 0}
- garden_area: {property_record.garden_area or 0}
- total_area: {property_record.total_area or 0}
- tags: {tag_names}

Style: {style}
Language: {language}
{rules_block}

Requirements:
- 5–7 sentences, natural and persuasive (not a bullet list, not raw data dumping)
- Focus on benefits: space, comfort, lifestyle, value
- Adapt tone:
  - luxury: premium, elegant, exclusive
  - family: warm, safe, convenient
  - investment: value, ROI, demand, rental potential
  - urgent: compelling, scarcity, fast decision
- Avoid unverifiable claims (no made-up amenities or locations)

Return ONLY the JSON object.
""".strip()

    def _build_description_prompt_from_payload(self, payload, *, style, language, rules):
        rules_block = f"\nAdditional rules from the user:\n{rules}\n" if rules else ""
        missing_block = ''
        if payload.get('missing_optional'):
            missing_block = (
                "\nMissing fields:\n"
                f"- {', '.join(payload['missing_optional'])}\n"
                "Do not mention or invent any missing information.\n"
            )
        return f"""
You are a professional real estate marketing expert.

You MUST return ONLY a single valid JSON object (no markdown, no code fences, no extra keys, no extra text) with exactly this schema:
{{
  "description": "<string>"
}}

Write a high-quality property description based on:

Property:
- title: {payload.get('name') or ''}
- property_type: {payload.get('property_type') or ''}
- price: {payload.get('expected_price') or 0}
- bedrooms: {payload.get('bedrooms') or 0}
- living_area: {payload.get('living_area') or 0}
- garden_area: {payload.get('garden_area') or 0}
- total_area: {payload.get('total_area') or 0}
- tags: {payload.get('tags') or ''}

Style: {style}
Language: {language}
{rules_block}{missing_block}

Requirements:
- 5–7 sentences, natural and persuasive (not a bullet list, not raw data dumping)
- Focus on benefits: space, comfort, lifestyle, value
- Adapt tone:
  - luxury: premium, elegant, exclusive
  - family: warm, safe, convenient
  - investment: value, ROI, demand, rental potential
  - urgent: compelling, scarcity, fast decision
- Avoid unverifiable claims (no made-up amenities or locations)

Return ONLY the JSON object.
""".strip()

    def _call_openrouter(self, prompt, *, expect_json=False):
        return OpenRouterProvider(self._get_config).generate(prompt, json_mode=bool(expect_json))

    def _call_gemini(self, prompt, *, expect_json=False):
        return GeminiProvider(self._get_config).generate(prompt)

    def _call_ollama(self, prompt, *, expect_json=False):
        return OllamaProvider(self._get_config).generate(prompt)

    def embed_text(self, text):
        provider = self._get_config('estate.embedding_provider', 'ollama')
        if provider != 'ollama':
            raise UserError('Only Ollama embedding provider is supported in this demo.')
        return OllamaProvider(self._get_config).embed(text or '')

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

    def _fallback_description(self, property_record, reason, provider, style, language):
        normalized_reason = self._normalize_reason(reason, provider)
        property_type = property_record.property_type_id.name if property_record.property_type_id else 'property'
        tags = ', '.join(property_record.tag_ids.mapped('name')) if property_record.tag_ids else ''
        bedrooms = property_record.bedrooms or 0
        total_area = property_record.total_area or 0
        expected_price = property_record.expected_price or 0

        if (language or '').lower().startswith('vi'):
            style_prefix = {
                'luxury': 'Đẳng cấp và tinh tế,',
                'family': 'Ấm cúng và an toàn,',
                'investment': 'Tối ưu giá trị đầu tư,',
                'urgent': 'Cơ hội hiếm có,',
            }.get(style, 'Ấn tượng và dễ thu hút,')
            tag_sentence = f'Điểm nhấn: {tags}.' if tags else 'Thiết kế linh hoạt, phù hợp nhiều nhu cầu.'
            description = (
                f"{style_prefix} {property_record.name or 'Bất động sản'} là một {property_type} đáng cân nhắc cho nhu cầu hiện tại của bạn. "
                f"Không gian {bedrooms} phòng ngủ cùng tổng diện tích khoảng {total_area:,.0f} m² mang lại sự thoải mái cho sinh hoạt và tiếp khách. "
                f"{tag_sentence} "
                f"Mức giá kỳ vọng {expected_price:,.0f} được đặt theo hướng cạnh tranh so với tiềm năng khai thác và khả năng tăng giá. "
                f"Liên hệ ngay để được tư vấn và sắp xếp lịch xem nhà."
            )
        else:
            style_prefix = {
                'luxury': 'Refined and upscale,',
                'family': 'Warm and welcoming,',
                'investment': 'Built for smart returns,',
                'urgent': 'A rare opportunity,',
            }.get(style, 'Compelling and market-ready,')
            tag_sentence = f"Highlights include {tags}." if tags else 'Thoughtfully designed for everyday comfort.'
            description = (
                f"{style_prefix} {property_record.name or 'This home'} is a {property_type} that balances lifestyle and value. "
                f"With {bedrooms} bedrooms and approximately {total_area:,.0f} m² of total space, it offers room to live, work, and relax. "
                f"{tag_sentence} "
                f"Priced around {expected_price:,.0f}, it stands out as a strong option for both end-users and long-term buyers. "
                f"Schedule a viewing soon to experience it in person."
            )

        return {
            'description': description,
            'provider': 'fallback',
            'style': style,
            'language': language,
            'reason': normalized_reason,
        }

    def _fallback_description_from_payload(self, payload, reason, provider, style, language):
        normalized_reason = self._normalize_reason(reason, provider)
        property_type = payload.get('property_type') or 'property'
        tags = payload.get('tags') or ''
        bedrooms = payload.get('bedrooms') or 0
        total_area = payload.get('total_area') or 0
        expected_price = payload.get('expected_price') or 0
        name = payload.get('name') or 'This property'

        if (language or '').lower().startswith('vi'):
            style_prefix = {
                'luxury': 'Đẳng cấp và tinh tế,',
                'family': 'Ấm cúng và an toàn,',
                'investment': 'Tối ưu giá trị đầu tư,',
                'urgent': 'Cơ hội hiếm có,',
            }.get(style, 'Ấn tượng và dễ thu hút,')
            tag_sentence = f'Điểm nhấn: {tags}.' if tags else 'Thiết kế linh hoạt, phù hợp nhiều nhu cầu.'
            description = (
                f"{style_prefix} {name} là một {property_type} đáng cân nhắc cho nhu cầu hiện tại của bạn. "
                f"Không gian {bedrooms} phòng ngủ cùng tổng diện tích khoảng {total_area:,.0f} m² mang lại sự thoải mái cho sinh hoạt và tiếp khách. "
                f"{tag_sentence} "
                f"Mức giá kỳ vọng {expected_price:,.0f} được đặt theo hướng cạnh tranh so với tiềm năng khai thác và khả năng tăng giá. "
                f"Liên hệ ngay để được tư vấn và sắp xếp lịch xem nhà."
            )
        else:
            style_prefix = {
                'luxury': 'Refined and upscale,',
                'family': 'Warm and welcoming,',
                'investment': 'Built for smart returns,',
                'urgent': 'A rare opportunity,',
            }.get(style, 'Compelling and market-ready,')
            tag_sentence = f"Highlights include {tags}." if tags else 'Thoughtfully designed for everyday comfort.'
            description = (
                f"{style_prefix} {name} is a {property_type} that balances lifestyle and value. "
                f"With {bedrooms} bedrooms and approximately {total_area:,.0f} m² of total space, it offers room to live, work, and relax. "
                f"{tag_sentence} "
                f"Priced around {expected_price:,.0f}, it stands out as a strong option for both end-users and long-term buyers. "
                f"Schedule a viewing soon to experience it in person."
            )

        return {
            'description': description,
            'provider': 'fallback',
            'style': style,
            'language': language,
            'reason': normalized_reason,
        }

    def _normalize_property_payload(self, values):
        missing_required = []
        missing_optional = []

        name = (values.get('name') or '').strip()
        if not name:
            missing_required.append('title')

        expected_price = values.get('expected_price')
        if expected_price in (None, False, 0, 0.0):
            missing_required.append('expected_price')

        property_type = (values.get('property_type') or '').strip()
        property_type_id = values.get('property_type_id')
        if not property_type and property_type_id:
            property_type = self.env['estate.property.type'].browse(int(property_type_id)).exists().name or ''
        if not property_type:
            missing_optional.append('property_type')

        tags = (values.get('tags') or '').strip()
        tag_ids = values.get('tag_ids') or []
        if not tags and tag_ids:
            tags = ', '.join(self.env['estate.property.tag'].browse(tag_ids).exists().mapped('name'))
        if not tags:
            missing_optional.append('tags')

        for field_name in ('bedrooms', 'living_area', 'garden_area', 'total_area'):
            if values.get(field_name) in (None, False, ''):
                missing_optional.append(field_name)

        return {
            'name': name,
            'property_type': property_type,
            'expected_price': expected_price or 0,
            'bedrooms': values.get('bedrooms') or 0,
            'living_area': values.get('living_area') or 0,
            'garden_area': values.get('garden_area') or 0,
            'total_area': values.get('total_area') or 0,
            'tags': tags,
            'missing_required': missing_required,
            'missing_optional': missing_optional,
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
