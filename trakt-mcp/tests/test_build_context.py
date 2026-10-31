"""Guard the explicit Docker context allowlist against missing runtime files."""

from pathlib import Path
import shlex


ROOT = Path(__file__).resolve().parents[1]


def test_docker_copy_sources_are_in_build_context():
    rules = ROOT.joinpath('.dockerignore').read_text().splitlines()
    # Keep this guard aligned with the intentionally simple deny-all allowlist.
    assert rules[0] == '*'
    assert all(rule.startswith('!') for rule in rules[1:] if rule)
    allowed = {rule[1:].rstrip('/') for rule in rules if rule.startswith('!')}
    for line in ROOT.joinpath('Dockerfile').read_text().splitlines():
        if not line.startswith('COPY '):
            continue
        for source in shlex.split(line)[1:-1]:
            assert ROOT.joinpath(source).exists(), f'Missing Docker source: {source}'
            assert source.rstrip('/') in allowed, f'Docker source excluded: {source}'
            if ROOT.joinpath(source).is_dir():
                assert source.rstrip('/') + '/**' in allowed


def test_docker_context_allowlist_has_no_missing_files():
    for rule in ROOT.joinpath('.dockerignore').read_text().splitlines():
        if rule.startswith('!') and '*' not in rule:
            assert ROOT.joinpath(rule[1:]).exists(), f'Stale Docker allowlist entry: {rule}'
