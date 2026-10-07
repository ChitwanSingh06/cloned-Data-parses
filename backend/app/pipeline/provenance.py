from app.models.block import Provenance
from app.models.document import Document
from app.utils.bbox import round_bbox


def add_provenance(document: Document) -> Document:
    pages = {p.page_number: p for p in document.pages}
    for b in document.blocks:
        srcs = b.meta.pop("sources", None)
        if not srcs:
            src = {"page": b.page, "bbox": b.bbox, "region_id": b.meta.get("region_id")}
            for key in ("source_type", "paragraph_index", "table_index", "image_index", "relationship_id", "slide_number", "shape_index"):
                if key in b.meta:
                    src[key] = b.meta[key]
            srcs = [src]
        clean = []
        for s in srcs:
            p = pages.get(s["page"])
            bb = s.get("bbox")
            if bb and p:  # clamp into page bounds
                bb = [max(0.0, bb[0]), max(0.0, bb[1]), min(p.width, bb[2]), min(p.height, bb[3])]
            item = {"page": s["page"], "bbox": round_bbox(bb), "region_id": s.get("region_id")}
            for key, value in s.items():
                if key not in item:
                    item[key] = value
            clean.append(item)
        b.bbox = round_bbox(b.bbox)
        b.provenance = Provenance(document=document.document_id, page=b.page, bbox=b.bbox, extractor=b.extractor,
                                  source_region_id=b.meta.get("region_id"), sources=clean)
        b.meta.pop("line_boxes", None)
    return document
