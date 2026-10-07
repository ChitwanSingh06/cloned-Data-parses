from app.pipeline.orchestrator import parse_pdf


def handle_pdf(path: str, **kw):
    return parse_pdf(path, **kw)
