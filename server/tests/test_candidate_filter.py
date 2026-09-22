"""
Unit tests for the pure cosine-similarity logic in candidate_filter.py.
No embedding API calls — vectors are supplied directly, mirroring the
pattern used for rag_fusion.py's semantic_deduplicate.
"""
from __future__ import annotations

from app.tools.candidate_filter import filter_pairs_by_similarity


class TestFilterPairsBySimilarity:

    def test_identical_vectors_survive(self):
        items = [[1.0, 0.0]]
        reqs = [[1.0, 0.0]]
        assert filter_pairs_by_similarity(items, reqs, threshold=0.3) == [(0, 0)]

    def test_orthogonal_vectors_dropped(self):
        items = [[1.0, 0.0]]
        reqs = [[0.0, 1.0]]
        assert filter_pairs_by_similarity(items, reqs, threshold=0.3) == []

    def test_threshold_boundary_is_inclusive(self):
        # cos similarity between [1,0] and [1,1]/sqrt(2) is exactly sqrt(2)/2 ~= 0.7071
        items = [[1.0, 0.0]]
        reqs = [[1.0, 1.0]]
        assert filter_pairs_by_similarity(items, reqs, threshold=0.7071) == [(0, 0)]
        assert filter_pairs_by_similarity(items, reqs, threshold=0.708) == []

    def test_empty_inputs_return_no_pairs(self):
        assert filter_pairs_by_similarity([], [[1.0, 0.0]]) == []
        assert filter_pairs_by_similarity([[1.0, 0.0]], []) == []

    def test_multiple_items_and_requirements(self):
        items = [[1.0, 0.0], [0.0, 1.0]]
        reqs = [[1.0, 0.0], [0.0, 1.0]]
        pairs = filter_pairs_by_similarity(items, reqs, threshold=0.9)
        assert set(pairs) == {(0, 0), (1, 1)}

    def test_zero_vector_does_not_crash(self):
        items = [[0.0, 0.0]]
        reqs = [[1.0, 0.0]]
        # normalized zero vector -> similarity 0, below any positive threshold
        assert filter_pairs_by_similarity(items, reqs, threshold=0.3) == []
