import re

CHART_WORDS = re.compile(r"\b(chart|graph|plot|trend|histogram|distribution|bar|pie|line|scatter|axis|growth|share|%)\b", re.I)


def looks_like_chart(figure_region: dict, caption_text: str = "") -> bool:
    """Heuristic only: vector path-heavy region with numeric labels, or caption wording."""
    labels = figure_region.get("embedded_text", [])
    numeric = sum(1 for t in labels if re.fullmatch(r"[\(\-–$]?[\d.,]+%?\)?", t.strip()))
    if figure_region.get("n_paths", 0) >= 15 and numeric >= 3:
        return True
    return bool(re.match(r"\s*(chart|graph|exhibit)\b", caption_text, re.I)) or bool(
        caption_text and re.search(r"\b(chart|graph|plot|histogram)\b", caption_text, re.I))


def detect_charts(*_args, **_kw) -> list[dict]:
    """Charts are identified from figure regions via looks_like_chart()."""
    return []
