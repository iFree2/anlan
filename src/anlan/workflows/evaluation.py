"""Small exact issue-set scorer; does not judge citation support or real-world safety."""


def score_issues(predicted: list[list[str]], expected: list[list[str]]) -> dict:
    predicted_set = {tuple(item) for item in predicted}
    expected_set = {tuple(item) for item in expected}
    tp = len(predicted_set & expected_set)
    fp = len(predicted_set - expected_set)
    fn = len(expected_set - predicted_set)
    return {
        "tp": tp, "fp": fp, "fn": fn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "exact_match": predicted_set == expected_set,
    }
