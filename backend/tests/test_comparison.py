from app.processing.comparison import compare_metrics

def test_compare_metrics():
    r=compare_metrics({"rugosity":1,"cover":{"coral":10}}, {"rugosity":1.5,"cover":{"coral":8,"algae":4}})
    assert r["rugosity_difference"] == 0.5
    assert r["coral_cover_change"]["coral"] == -2
