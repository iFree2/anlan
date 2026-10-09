"""小型精确问题集合评分器；不判断引用是否成立，也不判断真实世界安全性。"""


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
