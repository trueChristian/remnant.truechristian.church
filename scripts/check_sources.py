#!/usr/bin/env python3
"""Reject unhealthy or lossy upstream inputs before generating any site pages."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from content import load_content
from deployment import live_deployment, validated_source_revisions
from publication_inventory import assert_retains, baseline_inventory, validate_inventory


def check_inputs(source_report: dict, english: Path, translations: Path, languages: Path,
                 *, previous: dict | None, migration_snapshot: dict | None = None) -> dict:
    revisions = validated_source_revisions(source_report)
    model = load_content(english, translations, strict_translations=True, language_registry=languages)
    if (model['translation_status'] != 'ready' or model['source_revision'] != revisions['english']
            or model['translation_revision'] != revisions['translations']):
        raise ValueError('Refusing site build: exported content does not match the selected healthy source revisions')
    tags = {'en', *(language['tag'] for language in model['languages'].values())}
    inventory = validate_inventory({tag: [article['id'] for article in model['articles'].get(tag, [])]
                                    for tag in tags})
    assert_retains(baseline_inventory(previous, migration_snapshot), inventory)
    return {'ready': True, 'revisions': revisions,
            'article_counts': {tag: len(ids) for tag, ids in inventory.items()}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-report', type=Path, default=Path('.build/source-report.json'))
    parser.add_argument('--english', type=Path, default=Path('.build/english'))
    parser.add_argument('--translations', type=Path, default=Path('.build/translations'))
    parser.add_argument('--languages', type=Path, default=Path('.build/languages.json'))
    parser.add_argument('--migration-baseline', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'data/publication-baseline.json')
    args = parser.parse_args()
    sources = json.loads(args.source_report.read_text())
    validated_source_revisions(sources)  # Stop before even reading an unusable export.
    previous = live_deployment(fresh=True)
    migration = (json.loads(args.migration_baseline.read_text())
                 if isinstance(previous, dict) and 'article_inventory' not in previous else None)
    print(json.dumps(check_inputs(sources, args.english, args.translations, args.languages,
                                  previous=previous, migration_snapshot=migration), indent=2))


if __name__ == '__main__':
    main()
