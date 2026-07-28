def compare_metrics(a: dict, b: dict) -> dict:
    def diff_dict(k):
        aa=a.get(k,{}) or {}; bb=b.get(k,{}) or {}
        keys=sorted(set(aa)|set(bb)); return {x: round((bb.get(x,0) or 0)-(aa.get(x,0) or 0), 4) for x in keys}
    return {
        "rugosity_difference": round((b.get("rugosity",0) or 0)-(a.get("rugosity",0) or 0), 6),
        "surface_area_difference": round((b.get("surface_area",0) or 0)-(a.get("surface_area",0) or 0), 3),
        "coral_cover_change": diff_dict("cover"),
        "health_class_change": diff_dict("health"),
        "note":"Metric derived from processed reef outputs; review with original survey data before scientific use."
    }
