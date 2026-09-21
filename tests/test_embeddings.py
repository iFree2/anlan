import pytest


def test_vector_validation_rejects_wrong_shape_and_nonfinite():
    from anlan.knowledge.embeddings import validate_vectors
    assert validate_vectors([[1.0] + [0.0] * 511], 1)[0][0] == 1.0
    for data in ([[1.0]], [[float("inf")] * 512], [[True] * 512], []):
        with pytest.raises(ValueError):
            validate_vectors(data, 1)
