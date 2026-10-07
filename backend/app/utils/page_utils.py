def page_number_from_block(block: dict) -> int:
    return int(block.get("page", 0))
