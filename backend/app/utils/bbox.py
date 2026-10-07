from typing import Optional

BBox = list[float]


def bbox_area(bbox: Optional[BBox]) -> float:
    if not bbox or len(bbox) != 4:
        return 0.0
    x1, y1, x2, y2 = bbox
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def union(a: Optional[BBox], b: Optional[BBox]) -> Optional[BBox]:
    if not a:
        return b
    if not b:
        return a
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def intersection_area(a: BBox, b: BBox) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, w) * max(0.0, h)


def overlap_ratio(a: BBox, b: BBox) -> float:
    """Fraction of `a` covered by `b`."""
    area = bbox_area(a)
    return intersection_area(a, b) / area if area else 0.0


def round_bbox(b: Optional[BBox], nd: int = 2) -> Optional[BBox]:
    return [round(float(v), nd) for v in b] if b else b
