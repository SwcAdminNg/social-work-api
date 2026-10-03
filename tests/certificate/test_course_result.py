"""Overall course result that gates certificate issuance - see
CertificateService.evaluate_course_result. Repository access is stubbed, no DB."""

import uuid
from types import SimpleNamespace

import pytest

from app.modules.certificate.service import CertificateService, CourseResult
from app.modules.learning.repository import LearningRepository


@pytest.fixture
def stub_scores(monkeypatch):
    def _stub(scores: dict):
        async def fake(self, user_id, course_id):
            return scores

        monkeypatch.setattr(LearningRepository, "get_best_assessment_scores", fake)

    return _stub


async def _evaluate(pass_mark=70) -> CourseResult:
    course = SimpleNamespace(id=uuid.uuid4(), certificate_pass_mark_percentage=pass_mark)
    return await CertificateService(session=None).evaluate_course_result(uuid.uuid4(), course)


async def test_average_below_pass_mark_fails(stub_scores):
    stub_scores({uuid.uuid4(): 90.0, uuid.uuid4(): 40.0})  # average 65
    result = await _evaluate(pass_mark=70)
    assert result.score_percentage == 65.0
    assert not result.passed and not result.is_pending


async def test_average_at_pass_mark_passes(stub_scores):
    stub_scores({uuid.uuid4(): 100.0, uuid.uuid4(): 40.0})  # average 70
    assert (await _evaluate(pass_mark=70)).passed


async def test_unscored_assessment_is_pending_not_failed(stub_scores):
    stub_scores({uuid.uuid4(): 100.0, uuid.uuid4(): None})  # essay awaiting a released grade
    result = await _evaluate()
    assert result.is_pending
    assert not result.passed


async def test_course_without_assessments_passes(stub_scores):
    stub_scores({})
    assert (await _evaluate(pass_mark=100)).passed


async def test_missing_pass_mark_defaults_to_70(stub_scores):
    stub_scores({uuid.uuid4(): 69.0})
    result = await _evaluate(pass_mark=None)
    assert result.pass_mark_percentage == 70
    assert not result.passed
