from app.pipeline.failsafe import error_response


def build_error(code: str, message: str) -> dict:
    return error_response(code, message)
