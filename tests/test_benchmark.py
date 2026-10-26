import hashlib
import json
from pathlib import Path
import pytest
from benchmarks.analyze import normalize, score, distance


@pytest.mark.parametrize('written,spoken', [
    ('50%', 'fünfzig Prozent'),
    ('21 Grad', 'einundzwanzig Grad'),
    ('22,5 Grad', 'zweiundzwanzig Komma fünf Grad'),
    ('18:30 Uhr', 'achtzehn Uhr dreißig'),
    ('24,00 €', 'vierundzwanzig Euro'),
])
def test_number_normalization(written, spoken):
    assert normalize(written) == normalize(spoken)


def test_score_does_not_hide_name_errors():
    assert score('Jürgen Schneider', 'Jügenschneider')['word_errors'] == 2
    assert score('Bescheid', 'bescheit')['word_errors'] == 1
    assert distance([], ['extra']) == 1
    assert score('', '')['exact']


@pytest.mark.parametrize('directory', ['audio', 'audio-v2'])
def test_fixture_integrity(directory):
    root = Path('benchmarks') / directory
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    assert len(manifest) == 23
    assert len({e['id'] for e in manifest}) == 23
    for e in manifest:
        assert hashlib.sha256((root / e['file']).read_bytes()).hexdigest() == e['sha256']


def test_final_results_and_audit_coverage():
    root = Path('benchmarks/results')
    for mode, expected in [('http', 138), ('realtime', 36)]:
        rows = [json.loads(line) for line in (root / f'results-{mode}.jsonl').read_text(encoding='utf-8').splitlines()]
        assert len(rows) == expected
        assert all(r['seconds'] > 0 for r in rows)
        assert len({(r['id'], r['system'], r['repetition']) for r in rows}) == expected
    audit = json.loads((root / 'acoustic-audit.json').read_text(encoding='utf-8'))
    assert len(audit['clips']) == 14
    assert all('audit_text' in e for e in audit['clips'])
    assert sum(e['word_errors'] for e in audit['clips']) == 1  # explicitly disclosed spelling error
