"""Finite host-side arithmetic example. Not a model or a general optimization solver."""
from __future__ import annotations
import json
from headroom_recursion.clients import strict_json

ROWS = [('A',4,2,8),('B',5,3,13),('C',6,2,15),('D',3,2,9),
        ('E',7,4,21),('F',4,1,10),('G',5,2,14),('H',2,1,6),
        ('I',6,3,18),('J',3,1,8),('K',8,4,23),('L',4,2,12)]
REQUIRES = {'C': ['A'], 'E': ['B'], 'F': ['D'], 'I': ['H'], 'K': ['A','H']}
CONFLICTS = [('E','G'), ('C','J'), ('F','L')]


def check(answer: str) -> dict:
    try:
        obj = strict_json(answer)
        if type(obj) is not dict or set(obj) != {'selected'}:
            raise ValueError('Expected only selected.')
        selected = obj['selected']
        offered = {row[0] for row in ROWS}
        if (type(selected) is not list or any(type(x) is not str or x not in offered for x in selected)
                or len(set(selected)) != len(selected)):
            raise ValueError('Use unique offered labels.')
    except (ValueError, TypeError, RecursionError) as exc:
        return {'feasible': False, 'errors': [str(exc)]}
    picked = set(selected)
    cost, crew, value = (sum(row[i] for row in ROWS if row[0] in picked) for i in (1,2,3))
    missing = [[label, prerequisite] for label in picked for prerequisite in REQUIRES.get(label, [])
               if prerequisite not in picked]
    conflicts = [list(pair) for pair in CONFLICTS if set(pair) <= picked]
    errors = []
    if cost > 24: errors.append('Cost exceeds 24.')
    if crew > 12: errors.append('Crew exceeds 12.')
    if not picked & {'C','E','K'}: errors.append('Select at least one of C,E,K.')
    if missing: errors.append('Missing prerequisites.')
    if conflicts: errors.append('Conflicting projects.')
    return dict(feasible=not errors, selected=sorted(picked), cost=cost, crew=crew, value=value,
                errors=errors, missing=sorted(missing), conflicts=conflicts)


def reference() -> dict:
    # Host-only finite oracle, not disclosed to the acting model.
    feasible = []
    for mask in range(1 << len(ROWS)):
        selected = [row[0] for i,row in enumerate(ROWS) if mask & (1 << i)]
        result = check(json.dumps({'selected': selected}))
        if result['feasible']: feasible.append(result)
    best = max(row['value'] for row in feasible)
    return {'examined': 1 << len(ROWS), 'feasible': len(feasible), 'optimum': best,
            'witnesses': [r for r in feasible if r['value'] == best]}


if __name__ == '__main__':
    result = reference()
    assert result['examined'] == 4096 and result['feasible'] == 99 and result['optimum'] == 67
    print(json.dumps({'scope': 'Python enumeration, not a model answer', **result}, indent=2))
