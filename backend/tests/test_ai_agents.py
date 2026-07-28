from types import SimpleNamespace
from app.services.ai_agents import generate_reef_report, answer_reef_question
from app.processing.pipeline import STEPS


def fake_dataset(id="a", name="Processed Demo Reef A"):
    return SimpleNamespace(id=id, name=name, metrics_json={
        "rugosity": 1.23,
        "surface_area": 1234.5,
        "cover": {"coral": 42.0, "rock": 21.0, "sand": 19.0, "algae": 18.0},
        "health": {"healthy": 70.0, "bleached": 11.0, "dead": 8.0, "diseased": 11.0},
        "ai": {"image_quality": {"notes": ["Synthetic POC quality metrics only"]}},
    })


def test_ai_report_generation_contains_required_sections():
    result = generate_reef_report(fake_dataset())
    report = result["report"]
    assert "executive_summary" in report
    assert "reef_health_assessment" in report
    assert "limitations" in report


def test_question_answering_contains_answer_and_evidence():
    result = answer_reef_question(fake_dataset(), "How healthy is this reef?")
    assert result["answer"]
    assert result["evidence"]["healthy"] == 70.0


def test_pipeline_steps_include_ai_model_stages():
    assert "AI coral image segmentation" in STEPS
    assert "AI benthic cover classification" in STEPS
    assert "AI coral health classification" in STEPS
