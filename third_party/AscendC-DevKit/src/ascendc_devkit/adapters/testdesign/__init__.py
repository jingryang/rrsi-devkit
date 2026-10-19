"""L6 Adapters — test_design anti-corruption layer.

Translates the testdesign skill chain's spec-style CSV output into the
domain ``TestCase`` model. The external CSV format and the internal domain
model evolve independently; this boundary keeps them decoupled (step-4 §七.1).
"""

from .csv_to_testcases import parse_testcase_csv

__all__ = ["parse_testcase_csv"]
