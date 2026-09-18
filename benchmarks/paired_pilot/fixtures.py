"""Frozen synthetic repository tasks. Grading fixtures never enter model prompts."""
import ast
import json
import random
import re

CORRECT_MONEY = '''def parse_cents(text):
    if not isinstance(text, str):
        raise ValueError("amount must be text")
    s = text.strip()
    sign = -1 if s.startswith("-") else 1
    if s[:1] in ("-", "+"):
        s = s[1:]
    parts = s.split(".")
    if len(parts) > 2 or not parts[0] or not all("0" <= c <= "9" for c in parts[0]):
        raise ValueError("invalid amount")
    fraction = parts[1] if len(parts) == 2 else ""
    if len(parts) == 2 and (not 1 <= len(fraction) <= 2 or not all("0" <= c <= "9" for c in fraction)):
        raise ValueError("invalid fraction")
    return sign * (int(parts[0]) * 100 + int((fraction + "00")[:2]))
'''
BUGGY_MONEY = '''def parse_cents(text):
    return int(float(text) * 100)
'''
BUGGY_IMPORT = '''def import_rows(rows):
    seen = set()
    accepted = []
    for row in rows:
        identity = row["amount"]
        if identity not in seen:
            seen.add(identity)
            accepted.append(dict(row))
    return {"rows": accepted, "total_cents": sum(parse_cents(row["amount"]) for row in accepted)}
'''
GOLD_IMPORT = '''def import_rows(rows):
    seen = set()
    accepted = []
    total = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        supplier = row.get("supplier_id")
        tx = row.get("transaction_id")
        if not isinstance(supplier, str) or not supplier or not isinstance(tx, str) or not tx:
            continue
        try:
            cents = parse_cents(row.get("amount"))
        except ValueError:
            continue
        identity = (supplier, tx)
        if identity in seen:
            continue
        seen.add(identity)
        accepted.append(dict(row))
        total += cents
    return {"rows": accepted, "total_cents": total}
'''
SPEC = '''Implement the existing service.py without changing its public API.
parse_cents(text) accepts a string: optional leading +/-, ASCII digits, optional decimal point and one or two fractional digits; outer whitespace is allowed. Return exact integer cents, without floating-point rounding. Other inputs raise ValueError.
import_rows(rows) accepts a list. Skip non-dicts, missing/empty/non-string supplier_id or transaction_id, or invalid amounts. Replays have the SAME supplier_id AND transaction_id: retain the first VALID row in input order. Distinct transactions with equal amounts and equal transaction_id from different suppliers must survive. Invalid rows must not consume an identity. Do not mutate the input or its rows. Return exactly {"rows": retained original row dictionaries, "total_cents": integer sum}. Preserve extra row fields.
Also supply test_regression.py with a test_regression() function using asserts to catch the original replay bug; no test framework needed. It can import parse_cents and import_rows from service. Only these two files are editable; no network or filesystem work in submitted code. No eval/exec, reflection or process spawning. Python's decimal library is allowed; other external dependencies are not.'''
PUBLIC_CASES = [
    ("different_equal_amounts",[{"supplier_id":"s","transaction_id":x,"amount":"1.00"} for x in ("a","b")]),
    ("first_replay",[{"supplier_id":"s","transaction_id":"a","amount":x} for x in ("1.00","2.00")]),
    ("supplier_namespace",[{"supplier_id":x,"transaction_id":"a","amount":"3.00"} for x in ("s1","s2")]),
    ("invalid_before_valid",[{"supplier_id":"s","transaction_id":"a","amount":x} for x in ("bad","4.00")]),
    ("malformed_rows",[None,{}, {"supplier_id":"","transaction_id":"x","amount":"1"}, {"supplier_id":"s","transaction_id":"a","amount":"5","extra":"retain"}])
]
MONEY_PUBLIC = ["0.29", "-1.25", "  +10.5  "]

def reference_rows(rows):
    seen=set();kept=[];total=0
    for row in rows:
        if type(row) is not dict or any(type(row.get(k)) is not str or not row[k] for k in ('supplier_id','transaction_id')):continue
        value=row.get('amount')
        if type(value)is not str or re.fullmatch(r'[+-]?[0-9]+(?:\.[0-9]{1,2})?',value.strip())is None:continue
        text=value.strip();negative=text.startswith('-');text=text.lstrip('+-')
        a,_,b=text.partition('.');cents=int(a)*100+int((b+'00')[:2]);cents=-cents if negative else cents
        key=(row['supplier_id'],row['transaction_id'])
        if key not in seen:seen.add(key);kept.append(dict(row));total+=cents
    return {'rows':kept,'total_cents':total}

def private_cases(seed):
    rng=random.Random(seed);out=[]
    for j in range(12):
        rows=[]
        for i in range(18):
            rows.append({'supplier_id':'s'+str(rng.randrange(3)),'transaction_id':'t'+str(rng.randrange(6)),
                         'amount':rng.choice(['0.29','-2.50','3','bad','900719925474099.91','+1.2']), 'memo':f'{j}-{i}'})
        out.append((f'heldout_{j}',rows))
    out += [('bool_ids',[{'supplier_id':True,'transaction_id':'a','amount':'1'}]),
            ('nonstring_amount',[{'supplier_id':'s','transaction_id':'a','amount':1.2}])]
    return out

def vet(source, test=False):
    if type(source)is not str or len(source)>9000:raise ValueError('source limit')
    tree=ast.parse(source)
    allowed_imports={'decimal'}|({'service'} if test else set())
    forbidden={'exec','eval','compile','open','input','globals','locals','vars','getattr','setattr','delattr','breakpoint','help','exit','quit','object','super'}
    for n in tree.body:
        if not isinstance(n,(ast.FunctionDef,ast.Import,ast.ImportFrom)):
            raise ValueError('only functions and permitted imports at module scope')
    for n in ast.walk(tree):
        if isinstance(n,(ast.ClassDef,ast.AsyncFunctionDef,ast.Global,ast.Nonlocal,ast.With,ast.AsyncWith)):
            raise ValueError('unsupported executable construct')
        if isinstance(n,ast.Name) and (n.id in forbidden or n.id.startswith('__')):raise ValueError('forbidden name')
        if isinstance(n,ast.Attribute) and n.attr.startswith('_'):raise ValueError('private attribute')
        if isinstance(n,ast.Import) and any(a.name not in allowed_imports for a in n.names):raise ValueError('unapproved import')
        if isinstance(n,ast.ImportFrom) and (n.level or n.module not in allowed_imports or any(a.name=='*' for a in n.names)):raise ValueError('unapproved import')
        if isinstance(n,ast.FunctionDef) and (n.decorator_list or any(not isinstance(x,ast.Constant) for x in n.args.defaults)):raise ValueError('decorators or computed defaults not allowed')
    names={n.name for n in tree.body if isinstance(n,ast.FunctionDef)}
    required={'test_regression'} if test else {'parse_cents','import_rows'}
    if not required<=names:raise ValueError('required function missing')
    return True

EPISODES = [
    ('ledgerkit','Initial ledgerkit requirement: transaction_id is globally unique. In this project, deduplicate only by transaction_id. Retain the first valid row. Keep this working decision in your project notes.'),
    ('ledgerkit','Correction for ledgerkit: transaction_id is unique ONLY within a supplier. The current replay identity is the pair supplier_id + transaction_id, NOT transaction_id alone and NOT amount. Keep different suppliers and distinct transactions even when amounts match. This replaces the earlier global-ID rule. Retain the first valid occurrence.'),
    ('showcase','Separate project showcase: this demonstration groups rows by amount and currency, not supplier_id. The marker SHOWCASE_ONLY_9Z belongs only to showcase. Do not apply this rule to ledgerkit.'),
    ('ledgerkit','Unrelated ledgerkit maintenance: documentation spelling and screen-reader labels were reviewed. The deployment display label is September Candidate. This changes no transaction identity, accounting or replay rule.')
]
BATCH=[{'supplier_id':'s1','transaction_id':'t1','amount':'10.00'},
       {'supplier_id':'s2','transaction_id':'t1','amount':'10.00'},
       {'supplier_id':'s1','transaction_id':'t2','amount':'10.00'},
       {'supplier_id':'s1','transaction_id':'t1','amount':'99.00'},
       {'supplier_id':'s2','transaction_id':'t2','amount':'-2.00'}]
MEMORY_TASK='For ledgerkit, apply our CURRENT replay policy to this batch. Return key_fields (the identity fields), kept_indices (zero-based, in order), total_cents and a short source_explanation identifying the current decision versus the superseded one. Batch: '+json.dumps(BATCH,separators=(',',':'))

def memory_grade(obj):
    return {'key_fields_correct':len(obj.get('key_fields',[]))==2 and set(obj['key_fields'])=={'supplier_id','transaction_id'},
            'indices_correct':obj.get('kept_indices')==[0,1,2,4], 'total_correct':obj.get('total_cents')==2800,
            'scope_clean':'SHOWCASE_ONLY_9Z' not in json.dumps(obj)}
