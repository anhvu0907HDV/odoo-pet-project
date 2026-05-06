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

    def generate(self, prompt, *, json_mode=False):
        api_key = self._get_config('estate.openrouter_api_key')
        if not api_key:
            raise RuntimeError('OpenRouter API key is missing.')
        model = self._get_config('estate.openrouter_model', 'openrouter/free')
        payload = {
            'model': model,
            'messages': [{'role': 'user', 'content': prompt}],
            'temperature': 0.1,
        }
        if json_mode:
            payload['response_format'] = {'type': 'json_object'}
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


class OllamaProvider(BaseAiProvider):
    TIMEOUT = 60

    def generate(self, prompt):
        base_url = (self._get_config('estate.ollama_base_url', 'http://localhost:11434') or '').rstrip('/')
        model = self._get_config('estate.ollama_model', 'mistral')
        if not base_url:
            raise RuntimeError('Ollama base URL is missing.')
        payload = {
            'model': model,
            'prompt': prompt,
            'stream': False,
        }
        body = self._post_json(
            f'{base_url}/api/generate',
            payload,
            headers={'Content-Type': 'application/json'},
            timeout=self.TIMEOUT,
        )
        return body.get('response', '')

    def embed(self, text):
        base_url = (self._get_config('estate.ollama_base_url', 'http://localhost:11434') or '').rstrip('/')
        model = self._get_config('estate.ollama_embed_model', 'nomic-embed-text')
        if not base_url:
            raise RuntimeError('Ollama base URL is missing.')
        text = text or ''

        # Ollama API compatibility:
        # - Older versions: POST /api/embeddings -> {"embedding":[...]} with payload {"model","prompt"}
        # - Newer versions: POST /api/embed -> {"embeddings":[[...]]} with payload {"model","input"}
        try:
            body = self._post_json(
                f'{base_url}/api/embeddings',
                {'model': model, 'prompt': text},
                headers={'Content-Type': 'application/json'},
                timeout=self.TIMEOUT,
            )
            embedding = body.get('embedding')
            if isinstance(embedding, list) and embedding:
                return embedding
        except error.HTTPError as http_error:
            if http_error.code != 404:
                raw_body = self._read_http_error_body(http_error, 220)
                raise RuntimeError(f'Ollama embeddings request failed ({http_error.code}): {raw_body}') from http_error
        except Exception:
            # fall through to /api/embed
            pass

        try:
            body = self._post_json(
                f'{base_url}/api/embed',
                {'model': model, 'input': text},
                headers={'Content-Type': 'application/json'},
                timeout=self.TIMEOUT,
            )
            embeddings = body.get('embeddings')
            if isinstance(embeddings, list) and embeddings and isinstance(embeddings[0], list) and embeddings[0]:
                return embeddings[0]
            embedding = body.get('embedding')
            if isinstance(embedding, list) and embedding:
                return embedding
        except error.HTTPError as http_error:
            raw_body = self._read_http_error_body(http_error, 220)
            raise RuntimeError(f'Ollama embed request failed ({http_error.code}): {raw_body}') from http_error

        raise RuntimeError('Ollama embeddings returned empty embedding.')
