"""Optional LM Studio client for an already-loaded model on localhost.

No model loading, package installation, credentials, or hosted inference.
"""
from __future__ import annotations
import http.client
import json
import math
from .clients import CallResult, TransportError, strict_json
from .response_schema import schema_copy, UnsupportedStructuredOutput

class LMStudioClient:
    def __init__(self, port=1234, *, timeout_s=120):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('invalid local server port')
        if type(timeout_s) not in (int,float) or not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError('invalid timeout')
        self.port = port
        self.timeout_s = timeout_s

    def _request(self, method, path, payload=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=self.timeout_s)
        try:
            body = None if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
            connection.request(method, path, body=body, headers={'Content-Type':'application/json'})
            response = connection.getresponse()
            data = response.read(2_000_001)
            if response.status != 200 or len(data) > 2_000_000:
                raise TransportError('LM Studio response rejected: ' + str(response.status))
            return strict_json(data.decode('utf-8'))
        except (OSError, http.client.HTTPException, ValueError, UnicodeError) as exc:
            raise TransportError('local inference transport failed: ' + type(exc).__name__) from exc
        finally:
            connection.close()

    def loaded_model(self, model):
        if type(model) is not str or not model:
            raise ValueError('an explicit loaded model identifier is required')
        records = self._request('GET', '/api/v0/models')['data']
        matches = [m for m in records if m.get('id') == model and m.get('state') == 'loaded']
        if len(matches) != 1:
            raise UnsupportedStructuredOutput('the exact requested model is not already loaded')
        return matches[0]

    def check_schema(self, model, schema):
        schema_copy(schema)
        info = self.loaded_model(model)
        if info.get('compatibility_type') != 'gguf':
            raise UnsupportedStructuredOutput('this adapter qualifies only the GGUF grammar backend')
        return True

    def complete(self, *, model, system, user, max_tokens=2048, temperature=0.7,
                 use_headroom=False, response_schema=None):
        if use_headroom:
            raise ValueError('compression belongs to the controller, not this adapter')
        if type(max_tokens) is not int or not 1 <= max_tokens <= 65536:
            raise ValueError('invalid output token limit')
        if type(temperature) not in (int,float) or not math.isfinite(temperature) or not 0 <= temperature <= 2:
            raise ValueError('invalid temperature')
        info = self.loaded_model(model)
        if max_tokens >= info.get('loaded_context_length', 0):
            raise ValueError('output reservation exceeds the loaded context')
        body = {'model':model, 'messages':[{'role':'system','content':system},
                {'role':'user','content':user}], 'max_tokens':max_tokens,
                'temperature':temperature, 'stream':False}
        if response_schema is not None:
            if info.get("compatibility_type") != "gguf":
                raise UnsupportedStructuredOutput("this adapter requires the GGUF grammar backend")
            body['response_format'] = {'type':'json_schema', 'json_schema':
                {'name':'worker_response', 'strict':True, 'schema':schema_copy(response_schema)}}
        value = self._request('POST', '/v1/chat/completions', body)
        if self.loaded_model(model) != info:
            raise TransportError('loaded model configuration changed during generation')
        raw_usage = value.get('usage')
        usage = ({k:raw_usage[k] for k in ('prompt_tokens','completion_tokens','total_tokens') if k in raw_usage}
                 if type(raw_usage) is dict else None)
        choices = value.get('choices')
        if type(choices) is not list or len(choices) != 1:
            raise TransportError('expected one completion')
        choice = choices[0]
        message = choice.get('message', {})
        text = message.get('content')
        if message.get('refusal'):
            return CallResult(text or '', stop_reason='refusal', usage=usage)
        if type(text) is not str:
            raise TransportError('completion contains no text')
        reason = choice.get('finish_reason')
        stop = {'stop':'stop', 'length':'length'}.get(reason, 'error')
        # Raw text is returned. No fence stripping, JSON repair or parsed reserialization.
        return CallResult(text, stop_reason=stop, usage=usage)
