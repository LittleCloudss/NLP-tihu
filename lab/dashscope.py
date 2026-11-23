"""DashScope's Anthropic Messages transport for the multimodel experiment."""
import urllib.request
import json


MODELS = frozenset({'qwen', 'qwen4-max', 'qwen3.8-flash', 'deepseek-v4.1-flash-1017'})

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def request(messages, cfg, settings, provider='qwen'):
    spec = cfg['prices'][provider]
    base = settings.get('ANTHROPIC_BASE_URL', spec['base_url']).strip().rstrip('/')
    if base != spec['base_url']:
        raise ValueError('ANTHROPIC_BASE_URL must match the DashScope address in the experiment configuration.')
    model = spec['model']
    turns = []
    for message in messages[1:]:
        content = message['content']
        if isinstance(content, list):
            parts = []
            for block in content:
                if block['type'] == 'text':
                    parts.append(block)
                elif block['type'] == 'image_url':
                    url = block['image_url']['url']
                    prefix = 'data:image/png;base64,'
                    if not url.startswith(prefix):
                        raise ValueError('Expected an inline PNG screenshot.')
                    parts.append({'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': url[len(prefix):]}})
                else:
                    raise ValueError('Unknown message content type.')
            content = parts
        turns.append({'role': message['role'], 'content': content})
    body = {'model': model, 'system': messages[0]['content'], 'messages': turns,
            'max_tokens': cfg['max_output_tokens'], 'temperature': cfg['temperature'],
            'thinking': {'type': cfg['thinking']}}
    headers = {'Content-Type': 'application/json', 'x-api-key': settings['ANTHROPIC_AUTH_TOKEN'],
               'anthropic-version': '2023-06-01'}
    return urllib.request.Request(base + '/v1/messages', data=json.dumps(body).encode(), headers=headers), body


def usage(response):
    raw = response.get('usage') or {}
    return {**raw, 'prompt_tokens': raw.get('input_tokens'), 'completion_tokens': raw.get('output_tokens')}


def output_text(response):
    return ''.join(block['text'] for block in response['content'] if block['type'] == 'text')


def send(req, request_path):
    """Send the archived payload. The local credential travels only via stdin."""
    import io
    import subprocess
    import tempfile
    import urllib.error
    from pathlib import Path

    if req.full_url != 'https://dashscope.aliyuncs.com/apps/anthropic/v1/messages':
        raise ValueError('Unexpected DashScope endpoint.')
    with tempfile.TemporaryDirectory() as temp:
        response = Path(temp)/'reply.json'
        args = ['curl', '-q', '--silent', '--show-error', '--noproxy', '*',
                '--proto', '=https', '--connect-timeout', '20', '--max-time', '600',
                '--header', '@-', '--data-binary', '@'+str(request_path),
                '--output', str(response), '--write-out', '%{http_code}', req.full_url]
        header_lines = []
        for name, value in req.header_items():
            if '\r' in value or '\n' in value:
                raise ValueError('Invalid request header value.')
            header_lines.append(name+': '+value)
        result = subprocess.run(args, input=('\n'.join(header_lines)+'\n').encode(),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode:
            raise urllib.error.URLError(result.stderr.decode(errors='replace')[:300])
        status = int(result.stdout)
        if status != 200:
            raise urllib.error.HTTPError(req.full_url, status, 'DashScope response', None,
                                         io.BytesIO(response.read_bytes()[:2000]))
        return json.loads(response.read_bytes())
