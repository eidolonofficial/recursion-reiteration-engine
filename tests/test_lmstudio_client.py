"""Optional local transport: actual schema parameters, no fallback or auto-loading."""
import copy
import json
import unittest
from unittest.mock import patch,MagicMock
from headroom_recursion.lmstudio_client import LMStudioClient
from headroom_recursion.clients import TransportError
from headroom_recursion.response_schema import UnsupportedStructuredOutput
from test_structured_output import SCHEMA

class Native(LMStudioClient):
    def __init__(self):
        super().__init__();self.sent=[]
        self.info={'id':'loaded','state':'loaded','compatibility_type':'gguf','loaded_context_length':8192}
        self.reply={'choices':[{'message':{'content':'{"selected":["A"]}'},'finish_reason':'stop'}],
                    'usage':{'prompt_tokens':10,'completion_tokens':8,'total_tokens':18}}
    def _request(self, method, path, payload=None):
        self.sent.append((method,path,copy.deepcopy(payload)))
        return {'data':[self.info.copy()]} if method=='GET' else copy.deepcopy(self.reply)

class NativeTests(unittest.TestCase):
    def call(self, client, **options):
        values=dict(model='loaded',system='sys',user='task',max_tokens=128,temperature=0,response_schema=SCHEMA)
        values.update(options)
        return client.complete(**values)

    def test_schema_temperature_and_limit_reach_native_request(self):
        c=Native();result=self.call(c)
        body=next(p for method,path,p in c.sent if method=='POST')
        self.assertEqual(body['response_format']['json_schema']['schema'],SCHEMA)
        self.assertIs(body['response_format']['json_schema']['strict'],True)
        self.assertEqual(body['temperature'],0);self.assertEqual(body['max_tokens'],128)
        self.assertEqual(result.usage['total_tokens'],18)

    def test_raw_markdown_is_not_stripped(self):
        c=Native();c.reply['choices'][0]['message']['content']='```json\n{}\n```'
        self.assertEqual(self.call(c).text,'```json\n{}\n```')

    def test_length_and_refusal_remain_explicit(self):
        c=Native();c.reply['choices'][0]['finish_reason']='length'
        self.assertEqual(self.call(c).stop_reason,'length')
        c.reply['choices'][0]['message']['refusal']='no completion'
        self.assertEqual(self.call(c).stop_reason,'refusal')

    def test_not_loaded_and_unsupported_schema_never_start_generation(self):
        for change in ('not-loaded','schema','backend'):
            c=Native();schema=copy.deepcopy(SCHEMA)
            if change=='not-loaded':c.info['state']='not-loaded'
            elif change=='schema':schema['uniqueItems']=True
            else:c.info['compatibility_type']='unknown'
            with self.assertRaises(UnsupportedStructuredOutput):self.call(c,response_schema=schema)
            self.assertFalse(any(method=='POST' for method,_,_ in c.sent))

    def test_unconstrained_legacy_request_has_no_schema_field(self):
        c=Native();self.call(c,response_schema=None)
        body=next(p for method,_,p in c.sent if method=='POST')
        self.assertNotIn('response_format',body)

    def test_loopback_only_no_redirects_and_connection_closed(self):
        with patch('headroom_recursion.lmstudio_client.http.client.HTTPConnection') as connection:
            response=connection.return_value.getresponse.return_value
            response.status=302;response.read.return_value=b'{}'
            c=LMStudioClient(port=1234)
            with self.assertRaises(TransportError):c._request('GET','/api/v0/models')
            connection.assert_called_once_with('127.0.0.1',1234,timeout=120)
            connection.return_value.close.assert_called_once()

    def test_constructor_and_invalid_controls_do_not_connect(self):
        with patch('headroom_recursion.lmstudio_client.http.client.HTTPConnection') as connection:
            c=LMStudioClient()
            with self.assertRaises(ValueError):self.call(c,max_tokens=True)
            with self.assertRaises(ValueError):self.call(c,temperature=float('nan'))
            connection.assert_not_called()
        for port in (True,0,65536,'1234'):
            with self.assertRaises(ValueError):LMStudioClient(port)

if __name__=='__main__':unittest.main()
