import pytest

import make_fixtures as fx
from app.extractors.equations.math_layout import chars_to_latex
from app.models.block import BlockType
from app.output.markdown_builder import build_markdown
from app.pipeline.orchestrator import parse_pdf

BASE = "FV = PV \u00d7 (1+r)"
needs_font = pytest.mark.skipif(fx.unicode_font() is None, reason="needs a Unicode math font")


def _eq(tmp_path, items, rules=()):
    doc = parse_pdf(str(fx.equation_pdf(tmp_path / "e.pdf", items, rules)))
    eqs = [b for b in doc.blocks if b.type == BlockType.equation]
    return doc, eqs


def test_power_is_a_superscript_not_a_trailing_n(tmp_path):
    doc, eqs = _eq(tmp_path, [(100, 200, BASE, 12), (100 + fx.adv(BASE, 12), 195, "n", 8)])
    assert len(eqs) == 1
    e = eqs[0]
    assert e.content["latex"] == r"FV = PV \times (1+r)^{n}" and e.content["raw_text"].startswith("FV = PV")
    assert e.meta["recognizer"] == "span-geometry" and "scripts" in e.meta["structures"]
    assert e.bbox and e.provenance.page == 1 and e.confidence >= 0.6 and e.status.value == "OK"
    assert not [b for b in doc.blocks if b.type == BlockType.heading]


def test_markdown_renders_display_math_never_a_heading(tmp_path):
    doc, _ = _eq(tmp_path, [(100, 200, BASE, 12), (100 + fx.adv(BASE, 12), 195, "n", 8)])
    md = build_markdown(doc.model_dump(mode="json"))
    assert "$$\nFV = PV \\times (1+r)^{n}\n$$" in md
    assert "# FV" not in md and "(1+r)n" not in md


def test_subscripts(tmp_path):
    _, eqs = _eq(tmp_path, [(100, 200, "x", 12), (100 + fx.adv("x", 12), 203, "i", 8), (100 + fx.adv("x", 12) + fx.adv("i", 8), 200, " = y", 12),
                             (100 + fx.adv("x", 12) + fx.adv("i", 8) + fx.adv(" = y", 12), 203, "j", 8)])
    assert eqs and eqs[0].content["latex"] == "x_{i} = y_{j}"


def test_not_blind_same_size_same_baseline_is_not_a_power(tmp_path):
    chars = [dict(c=ch, x0=10 + 7 * i, x1=16 + 7 * i, y0=0, y1=10, oy=10.0, ox=10 + 7 * i, size=12.0, font="x") for i, ch in enumerate("Y=X2")]
    assert chars_to_latex(chars, [])["latex"] == "Y=X2"
    small_far = chars[:3] + [dict(chars[3], c="2", size=7.0, oy=5.0, x0=70, x1=75, ox=70)]  # raised+small but NOT attached
    assert chars_to_latex(small_far, [])["latex"] == "Y=X2"


@needs_font
def test_unicode_superscript_and_greek_and_operators(tmp_path):
    _, eqs = _eq(tmp_path, [(100, 200, "A = P(1+r)\u207f, \u03b1 \u2264 \u03b2 \u2260 \u03b3 \u00b1 \u03b4", 12, "uni")])
    assert eqs
    assert eqs[0].content["latex"] == r"A = P(1+r)^{n}, \alpha \leq \beta \neq \gamma \pm \delta"


@needs_font
def test_summation_with_limits(tmp_path):
    doc, eqs = _eq(tmp_path, [(100, 205, "\u2211", 20, "uni"), (100 + (fx.adv("\u2211", 20, True) - fx.adv("n", 8)) / 2, 188, "n", 8),
                             (100 + (fx.adv("\u2211", 20, True) - fx.adv("i=1", 8)) / 2, 219, "i=1", 8),
                             (104 + fx.adv("\u2211", 20, True), 205, "x", 12), (104 + fx.adv("\u2211", 20, True) + fx.adv("x", 12), 208, "i", 8),
                             (104 + fx.adv("\u2211", 20, True) + fx.adv("x", 12) + fx.adv("i", 8), 205, " = S", 12)])
    assert len(eqs) == 1 and eqs[0].content["latex"] == r"\sum_{i=1}^{n} x_{i} = S"
    assert not [b for b in doc.blocks if b.type == BlockType.paragraph and b.content in ("n", "i=1")]


def test_fraction_from_rule_and_stacked_text(tmp_path):
    doc, eqs = _eq(tmp_path, [(100, 205, "x =", 12), (136, 198, "a+b", 12), (136 + (fx.adv("a+b", 12) - fx.adv("c", 12)) / 2, 218, "c", 12)],
                      rules=[(134, 138 + fx.adv("a+b", 12), 203)])
    assert len(eqs) == 1 and eqs[0].content["latex"] == r"x = \frac{a+b}{c}"


@needs_font
def test_square_root_with_overline_and_inline(tmp_path):
    _, eqs = _eq(tmp_path, [(100, 200, "y = \u221a", 12, "uni"), (100 + fx.adv("y = \u221a", 12, True), 200, "x+1", 12)],
                      rules=[(100 + fx.adv("y = \u221a", 12, True) - 0.5, 100 + fx.adv("y = \u221a", 12, True) + fx.adv("x+1", 12), 189.5)])
    assert eqs and eqs[0].content["latex"] == r"y = \sqrt{x+1}"
    _, eqs2 = _eq(tmp_path, [(100, 200, "z = \u221a(a+b)", 12, "uni")])
    assert eqs2[0].content["latex"] == r"z = \sqrt{a+b}"


def test_unrecognised_equation_stays_a_flagged_block(tmp_path, monkeypatch):
    import app.extractors.equations.equation_extractor as ee
    monkeypatch.setattr(ee, "page_region_to_latex", lambda p, b: {"latex": None, "unmapped": [], "structures": []})
    monkeypatch.setattr(ee, "_pix2tex", lambda: None)
    doc, eqs = _eq(tmp_path, [(100, 200, BASE, 12), (100 + fx.adv(BASE, 12), 195, "n", 8)])
    e = eqs[0]
    assert e.content["latex"] is None and e.status.value == "REVIEW_REQUIRED" and e.meta["image_path"]
    md = build_markdown(doc.model_dump(mode="json"))
    assert "Unrecognized equation" in md and "$$" not in md and "\n#" not in md
