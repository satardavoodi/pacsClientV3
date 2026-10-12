"""Keep the regression catalog publishable after reversible encoding recovery."""
from pathlib import Path
import re

CATALOG = Path(__file__).resolve().parents[3] / 'docs/plans/architecture/REGRESSION_CATALOG.md'


def test_regression_catalog_does_not_expand_beyond_document_size_budget():
    assert CATALOG.stat().st_size < 5 * 1024 * 1024, (
        'Regression catalog exceeds its document budget; inspect repeated text encoding '
        'before release rather than pushing a generated oversized blob.'
    )


def test_regression_catalog_has_no_exponentially_reencoded_character_run():
    text = CATALOG.read_text(encoding='utf-8')
    assert re.search(r'[^\x00-\x7f]{4096}', text) is None, (
        'Regression catalog contains an implausibly long non-ASCII run; '
        'preserve a backup and verify reversible encoding recovery.'
    )
