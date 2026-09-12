"""A bounded JSON-Schema subset, not a general schema interpreter."""
from __future__ import annotations
import json
import math
from .clients import TransportError, strict_json

class UnsupportedStructuredOutput(ValueError):
    pass

class InvalidStructuredOutput(TransportError):
    pass


def schema_copy(schema):
    try:
        encoded = json.dumps(schema, ensure_ascii=False, allow_nan=False)
        if len(encoded) > 32768:
            raise ValueError('response schema exceeds 32768 characters')
        result = strict_json(encoded)
        def visit(s, depth=0):
            if type(s) is not dict or depth > 12:
                raise ValueError('invalid or deeply nested schema')
            if 'anyOf' in s:
                if set(s) != {'anyOf'} or type(s['anyOf']) is not list or not 1 <= len(s['anyOf']) <= 8:
                    raise ValueError('invalid schema alternatives')
                for child in s['anyOf']: visit(child, depth+1)
                return
            kind = s.get('type')
            allowed = {'object': {'properties','required','additionalProperties'},
                       'array': {'items','minItems','maxItems'},
                       'string': {'minLength','maxLength'},
                       'integer': {'minimum','maximum'}, 'number': {'minimum','maximum'},
                       'boolean': set(), 'null': set()}
            if type(kind) is not str or kind not in allowed or set(s) - ({'type','enum'} | allowed[kind]):
                raise ValueError('unsupported response-schema type or keyword')
            if 'enum' in s:
                values = s['enum']
                if type(values) is not list or not values or len(values)>256 or kind in {'object','array'}:
                    raise ValueError('invalid scalar enum')
                for value in values: validate_value(value, {'type':kind})
            if kind=='object':
                props, req = s.get('properties'), s.get('required')
                if (type(props) is not dict or len(props)>128 or any(type(k) is not str for k in props) or type(req) is not list or
                    any(type(k) is not str for k in req) or len(set(req))!=len(req) or
                    not set(req)<=set(props) or s.get('additionalProperties') is not False):
                    raise ValueError('closed objects need properties and explicit required keys')
                for child in props.values(): visit(child, depth+1)
            elif kind=='array': visit(s.get('items'), depth+1)
            for lo,hi in (('minItems','maxItems'),('minLength','maxLength'),('minimum','maximum')):
                for key in (lo,hi):
                    if key in s:
                        value=s[key]
                        if type(value) not in (int,float) or not math.isfinite(value):
                            raise ValueError('invalid numeric schema bound')
                        if key not in {'minimum','maximum'} and (type(value) is not int or not 0<=value<=64000):
                            raise ValueError('invalid size bound')
                if lo in s and hi in s and s[lo]>s[hi]: raise ValueError('inverted bounds')
        visit(schema)
        visit(result)
        return result
    except (InvalidStructuredOutput,ValueError,TypeError,RecursionError,OverflowError) as exc:
        raise UnsupportedStructuredOutput(str(exc)) from exc


def validate_value(value, schema, path='$'):
    if 'anyOf' in schema:
        for child in schema['anyOf']:
            try: validate_value(value,child,path);return
            except InvalidStructuredOutput: pass
        raise InvalidStructuredOutput(path+': no permitted alternative')
    kind=schema['type']
    types={'object':dict,'array':list,'string':str,'integer':int,'boolean':bool,'null':type(None)}
    ok=(type(value) in (int,float) and math.isfinite(value)) if kind=='number' else type(value) is types[kind]
    if not ok: raise InvalidStructuredOutput(path+': wrong JSON type')
    if 'enum' in schema and not any(type(value) is type(x) and value==x for x in schema['enum']):
        raise InvalidStructuredOutput(path+': value is not offered')
    if kind=='object':
        props=schema.get('properties',{})
        if not set(schema.get('required',()))<=set(value) or set(value)-set(props):
            raise InvalidStructuredOutput(path+': missing or extra fields')
        for key,item in value.items(): validate_value(item,props[key],path+'.'+key)
    if kind=='array':
        for item in value: validate_value(item,schema['items'],path+'[]')
    lo,hi=({'array':('minItems','maxItems'),'string':('minLength','maxLength')}.get(kind,('minimum','maximum')))
    magnitude=len(value) if kind in {'string','array'} else value
    if (lo in schema and magnitude<schema[lo]) or (hi in schema and magnitude>schema[hi]):
        raise InvalidStructuredOutput(path+': outside declared bounds')


def parse_payload(text, schema):
    try:
        if type(text) is not str or len(text)>1_000_000: raise ValueError('response size/type')
        value=strict_json(text)
        validate_value(value,schema)
        return value
    except (ValueError,TypeError,RecursionError,OverflowError) as exc:
        raise InvalidStructuredOutput('invalid schema-bound payload: '+str(exc)) from exc


def require_schema(client, model, schema):
    checked=schema_copy(schema)
    preflight=getattr(client,'check_schema',None)
    if not callable(preflight):
        raise UnsupportedStructuredOutput('backend has no schema-constrained generation path')
    if preflight(model, schema_copy(checked)) is not True:
        raise UnsupportedStructuredOutput('backend did not confirm schema support')
    return checked
