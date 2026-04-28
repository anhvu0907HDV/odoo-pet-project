import json
from urllib import error, request


class BaseAiProvider:
    def __init__(self, get_config):
        self._get_config = get_config

    def _post_json(self, url, payload, *, headers, timeout):
        req = request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers=headers,
            method='POST',
        )
        with request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode('utf-8'))

    def _read_http_error_body(self, http_error, max_len):
        return http_error.read().decode('utf-8', errors='ignore')[:max_len]


class OpenRouterProvider(BaseAiProvider):
    URL = 'https://openrouter.ai/api/v1/chat/completions'
    TIMEOUT = 25

    def generate(self, prompt):
        api_key = self._get_config('estate.openrouter_api_key')
        if not api_key:
            raise RuntimeError('OpenRouter API key is missing.')
        model = self._get_config('estate.openrouter_model', 'openrouter/free')
        payload = {
            'model': model,
            'messages': [{'role': 'user', 'content': prompt}],
            'temperature': 0.1,
            'response_format': {'type': 'json_object'},
        }
        try:
            body = self._post_json(
                self.URL,
                payload,
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {api_key}',
                },
                timeout=self.TIMEOUT,
            )
            return body.get('choices', [{}])[0].get('message', {}).get('content', '')
        except error.HTTPError as http_error:
            raw_body = self._read_http_error_body(http_error, 180)
            if http_error.code == 429:
                raise RuntimeError('OpenRouter quota/rate limit exceeded (HTTP 429).') from http_error
            if http_error.code in (401, 403):
                raise RuntimeError('OpenRouter API key is invalid or unauthorized.') from http_error
            raise RuntimeError(f'OpenRouter request failed ({http_error.code}): {raw_body}') from http_error


class GeminiProvider(BaseAiProvider):
    TIMEOUT = 20

    def generate(self, prompt):
        api_key = self._get_config('estate.gemini_api_key') or self._get_config('gemini_api_key')
        if not api_key:
            raise RuntimeError('Gemini API key is missing.')
        model_name = self._get_config('estate.gemini_model', 'gemini-2.0-flash')
        payload = {
            'contents': [{'parts': [{'text': prompt}]}],
            'generationConfig': {'temperature': 0.1},
        }

        http_codes = []
        details = []
        for endpoint in self._endpoints(model_name):
            try:
                body = self._post_json(
                    f'{endpoint}?key={api_key}',
                    payload,
                    headers={'Content-Type': 'application/json'},
                    timeout=self.TIMEOUT,
                )
                return self._extract_text(body)
            except error.HTTPError as http_error:
                http_codes.append(http_error.code)
                details.append(f'{endpoint} -> {http_error.code} {self._read_http_error_body(http_error, 140)}')
            except Exception as exception:
                details.append(f'{endpoint} -> {exception}')

        if 429 in http_codes:
            raise RuntimeError('Gemini quota exceeded (HTTP 429).')
        if 401 in http_codes or 403 in http_codes:
            raise RuntimeError('Gemini API key is invalid or unauthorized.')
        if 404 in http_codes:
            raise RuntimeError('Gemini model not found. Check Gemini Model setting.')
        raise RuntimeError(f'Gemini request failed. {" | ".join(details)}')

    def _endpoints(self, model_name):
        return [
            f'https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent',
            f'https://generativelanguage.googleapis.com/v1/models/{model_name}:generateContent',
        ]

    def _extract_text(self, body):
        return (
            body.get('candidates', [{}])[0]
            .get('content', {})
            .get('parts', [{}])[0]
            .get('text', '')
        )
