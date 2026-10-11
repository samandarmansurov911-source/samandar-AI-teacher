import re, json, sys, os
D = os.path.dirname(os.path.abspath(__file__))

def low(w):
    return w.replace('I', 'ı').replace('İ', 'i').lower()

# ---- dictionary ----
forms = {}      # form -> [uz, lemma]
lemmas = {}     # lemma -> {uz, kind}
for fn in ['dict1.txt', 'dict2.txt', 'dict3.txt', 'dict4.txt', 'names.txt']:
    cur = None
    for raw in open(os.path.join(D, fn), encoding='utf8'):
        line = raw.strip()
        if not line or '=' not in line:
            continue
        left, uz = [s.strip() for s in line.split('=', 1)]
        if left.startswith('@'):
            left = left[1:]
            kind = ''
            while left[:1] in '~!':
                kind += left[0]; left = left[1:]
            cur = left
            lemmas[cur] = {'uz': uz, 'k': kind}
            forms.setdefault(cur, [uz, cur])
        else:
            if cur is None:
                sys.exit('form without lemma: ' + line)
            forms[left] = [uz, cur]

# ---- lessons ----
lessons = []
for raw in open(os.path.join(D, 'texts.txt'), encoding='utf8'):
    line = raw.rstrip('\n')
    if not line.strip():
        continue
    if line.startswith('# '):
        lessons.append({'title': line[2:], 'blocks': [], 'q': [], 'd': []})
        continue
    tag, rest = line.split('|', 1)
    L = lessons[-1]
    if tag == 'S':
        sp, tx = rest.split('|', 1)
        L['blocks'].append(['S', sp, tx])
    elif tag == 'P':
        L['blocks'].append(['P', '', rest])
    elif tag == 'Q':
        L['q'].append(rest)
    elif tag == 'D':
        L['d'].append(rest)
answers = [l.rstrip('\n').split('|') for l in open(os.path.join(D, 'answers.txt'), encoding='utf8') if l.strip()]
assert len(answers) == len(lessons) == 26, (len(answers), len(lessons))
for L, a in zip(lessons, answers):
    n = len(L['q']) + len(L['d'])
    assert len(a) == n, (L['title'], len(a), n)
    L['a'] = a

WORD = re.compile(r"[A-Za-zÇĞİÖŞÜçğıöşüâÂîûÎÛ]+(?:'[A-Za-zÇĞİÖŞÜçğıöşüâîû]+)?")

def lookup(w):
    w = low(w)
    for cand in (w, w.replace('ı', 'i'), w.split("'")[0], w.split("'")[0].replace('ı', 'i')):
        if cand in forms:
            return cand
    return None

missing = {}
for L in lessons:
    texts = [L['title']] + [b[2] for b in L['blocks']] + [b[1] for b in L['blocks']] + L['q'] + L['d'] + L['a']
    vocab = []
    for t in texts[: 1 + 2 * len(L['blocks'])]:
        pass
    seen = set()
    for t in [L['title']] + [b[2] for b in L['blocks']]:
        for w in WORD.findall(t):
            k = lookup(w)
            if not k:
                missing.setdefault(low(w), L['title']); continue
            lem = forms[k][1]
            info = lemmas.get(lem, {'k': ''})
            if '~' in info['k'] or '!' in info['k'] or lem in seen:
                continue
            seen.add(lem)
            vocab.append(lem)
    for t in texts:
        for w in WORD.findall(t):
            if not lookup(w):
                missing.setdefault(low(w), L['title'])
    L['vocab'] = vocab

if missing:
    for w, t in sorted(missing.items()):
        print('MISSING', w, '|', t)
    sys.exit(1)

data = {'lessons': lessons, 'forms': forms, 'lemmas': {k: v['uz'] for k, v in lemmas.items()}}
tpl = open(os.path.join(D, 'template.html'), encoding='utf8').read()
out = tpl.replace('/*DATA*/null', json.dumps(data, ensure_ascii=False, separators=(',', ':')))
open(os.path.join(D, '..', 'index.html'), 'w', encoding='utf8').write(out)
print('ok', len(forms), 'forms,', sum(len(L['vocab']) for L in lessons), 'vocab entries')
