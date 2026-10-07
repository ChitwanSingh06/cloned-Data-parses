def extract_chart(region: dict) -> dict:
    """Honest placeholder: the chart is preserved as an image; values are NOT read off the plot.

    Only text that is actually printed inside the chart region (axis ticks, legends, data labels)
    is reported. Quantitative extraction would need a chart-to-table model (e.g. DePlot/MatCha).
    """
    return {"signals": {"chart_detection": float(region.get("confidence", 0.55)), "chart_understanding": 0.3},
            "meta": {"data": None, "data_extracted": False,
                     "visible_labels": region.get("embedded_text", []),
                     "review_reason": "Chart values not extracted; refer to the preserved image."}}
