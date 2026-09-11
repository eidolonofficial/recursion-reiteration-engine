"""Create a deterministic 100-rung source-audit fixture, not a reasoning benchmark."""
from __future__ import annotations
import argparse
import ast
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess

BASE = '8654c7a772c015a867b0804b352f4c09bf10fe3a'


def create(source: Path, output: Path, revision: str = BASE) -> dict:
    if output.exists():
        raise ValueError('Refusing to overwrite an existing fixture')
    def read(name):
        if revision:
            return subprocess.check_output(['git', '-C', str(source), 'show', revision+':'+name]).decode('utf-8')
        path = (source/name).resolve()
        if source.resolve() not in path.parents:
            raise ValueError('Source escapes supplied directory')
        return path.read_text(encoding='utf-8')
    def digest(text):
        return hashlib.sha256(text.encode('utf-8')).hexdigest()
    manifest = json.loads(read('EXPORT_MANIFEST.json'))
    names = [n for n in manifest['files'] if n.endswith('.py') or n.startswith('references/')]
    records = [{'name': n, 'identity': manifest['files'][n],
                'scope': 'exact source file bytes, not execution correctness'} for n in names]
    for name in names:
        if not name.endswith('.py'):
            continue
        text = read(name)
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                segment = ast.get_source_segment(text, node)
                records.append({'name': name+':'+str(node.lineno)+':'+node.name,
                                'identity': digest(segment),
                                'scope': 'exact syntax bytes, not execution correctness'})
        if len(records) >= 100:
            break
    records = records[:100]
    if len(records) != 100:
        raise ValueError('Source does not provide 100 records')
    context = [{'path': n, 'text': read(n)} for n in names if n.startswith('references/')]
    old = {('base_'+str(i)): manifest['files'][n] for i, n in enumerate(names[:23])}
    seed = json.dumps({'certificates': old, 'established': context, 'latest': 'none',
                      'progress': 0, 'target_status': 'unresolved'}, ensure_ascii=False, sort_keys=True)
    current = seed; plan = []; stages = []
    for i, record in enumerate(records, 1):
        prefix = '"certificates": {'; insert = current.index(prefix)+len(prefix)
        a = current.index('"latest": ')+len('"latest": ')
        b = json.JSONDecoder().raw_decode(current[a:])[1]+a
        match = re.search(r'"progress": (\d+)', current); c, d = match.span(1)
        entry = json.dumps('audit_'+str(i))+': '+json.dumps(record, ensure_ascii=False, sort_keys=True)+', '
        edits = [{'start': insert, 'end': insert, 'text': entry},
                 {'start': a, 'end': b, 'text': json.dumps(record['identity'])},
                 {'start': c, 'end': d, 'text': str(i)}]
        out = []; cursor = 0
        for e in edits:
            out.extend([current[cursor:e['start']], e['text']]); cursor = e['end']
        current = ''.join(out)+current[cursor:]
        if json.loads(current)['progress'] != i:
            raise ValueError('Fixture reconstruction failed')
        obligation = 'Retain exact registered source identity for '+record['name']
        plan.append({'name': 'source-audit-'+str(i), 'obligation': obligation})
        stages.append({'notes': [obligation, 'Source identity '+record['identity']+'. No execution or proof claim.'], 'edits': edits})
    obj = {'schema': 2, 'problem': 'Preserve the exact archived design record. Add one measured source identity per stage; do not infer correctness or claim mathematical proof.',
           'seed': seed, 'seed_notes': 'Keep archived source bytes exact. Audit identity only.',
           'plan': plan, 'stages': stages, 'final_sha256': digest(current)}
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True).encode('utf-8')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as f:
        f.write(gzip.compress(raw, mtime=0))
    return {'fixture_sha256': hashlib.sha256(raw).hexdigest(), 'final_sha256': digest(current),
            'stages': 100, 'scope': 'Constructed source-audit workload, not neural inference or P=NP experiments.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--revision', default=BASE, help='Empty string reads an extracted base snapshot')
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(create(args.source, args.out, args.revision), sort_keys=True))
