from pathlib import Path
import hashlib, json, os, re

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path(os.environ.get('BRIX_VIDEO_CACHE', Path.home()/'.cache/brix-video'))

def path(value):
    p = Path(value).expanduser()
    return p.resolve() if p.is_absolute() else (ROOT/p).resolve()

def load_json(filename):
    return json.loads(Path(filename).read_text(encoding='utf-8'))

def save_json(filename, value):
    p = Path(filename)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')

def fingerprint(filename):
    p = Path(filename).resolve()
    s = p.stat()
    return {'path': str(p), 'size': s.st_size, 'modified_ns': s.st_mtime_ns}

def content_fingerprint(filename):
    p = Path(filename).resolve()
    h = hashlib.sha256()
    with p.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return {'size': p.stat().st_size, 'sha256': h.hexdigest()}

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:24]

def normalized(word):
    return re.sub(r'[^a-z0-9]', '', word.casefold().replace('’', "'"))

def validate_words(words, duration=None):
    if not words:
        raise ValueError('The word timing file is empty.')
    previous = 0.0
    for w in words:
        if not w.get('word') or not 0 <= w['start'] < w['end']:
            raise ValueError(f'Invalid word timing: {w}')
        if w['start'] < previous-.011:
            raise ValueError(f'Overlapping word timing: {w}')
        previous = w['end']
    if duration is not None and previous > duration+.1:
        raise ValueError('Word timings extend beyond the voiceover. Use matching timing data.')

def phrase_index(words, phrase, occurrence=None):
    haystack = [normalized(w['word']) for w in words]
    needle = [normalized(w) for w in phrase.split()]
    matches = [i for i in range(len(haystack)-len(needle)+1) if haystack[i:i+len(needle)] == needle]
    if not matches:
        raise ValueError(f'Timing anchor not found in transcript: {phrase!r}')
    if occurrence is None and len(matches) != 1:
        raise ValueError(f'Ambiguous timing anchor {phrase!r}; specify a zero-based occurrence.')
    try:
        return matches[occurrence or 0], len(needle)
    except IndexError as exc:
        raise ValueError(f'No such occurrence of timing anchor: {phrase!r}') from exc

def resolve_time(value, words, duration):
    if isinstance(value, (int, float)):
        result = float(value)
    elif value == 'start':
        result = 0.0
    elif value == 'end':
        result = duration
    elif isinstance(value, dict) and 'end_offset' in value:
        result = duration+value['end_offset']
    elif isinstance(value, dict) and 'phrase' in value:
        i, n = phrase_index(words, value['phrase'], value.get('occurrence'))
        result = words[i+n-1]['end'] if value.get('edge') == 'end' else words[i]['start']
        result += value.get('offset', 0)
    else:
        raise ValueError(f'Invalid timing anchor: {value!r}')
    if not 0 <= result <= duration:
        raise ValueError(f'Timing anchor {value!r} resolves outside the video: {result:.3f}s')
    return result

def timestamp(t, srt=False):
    factor = 1000 if srt else 100
    n = round(t*factor)
    return (f'{n//(3600*factor):02}:{n//(60*factor)%60:02}:{n//factor%60:02}'
            + (f',{n%factor:03}' if srt else f'.{n%factor:02}'))
