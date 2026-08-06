from __future__ import annotations

import pytest

from energy_forecast.jobs.domain import (
    InvalidJobTransitionError,
    JobStatus,
    validate_transition,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (JobStatus.QUEUED, JobStatus.RUNNING),
        (JobStatus.QUEUED, JobStatus.CANCEL_REQUESTED),
        (JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED),
        (JobStatus.RUNNING, JobStatus.SUCCEEDED),
        (JobStatus.RUNNING, JobStatus.FAILED),
        (JobStatus.RUNNING, JobStatus.STALE),
        (JobStatus.CANCEL_REQUESTED, JobStatus.CANCELLED),
        (JobStatus.STALE, JobStatus.QUEUED),
        (JobStatus.STALE, JobStatus.FAILED),
        (JobStatus.FAILED, JobStatus.QUEUED),
    ],
)
def test_accepted_job_transitions(current: JobStatus, target: JobStatus) -> None:
    validate_transition(current, target)


@pytest.mark.parametrize(
    "terminal",
    [JobStatus.CANCELLED, JobStatus.SUCCEEDED],
)
@pytest.mark.parametrize("target", list(JobStatus))
def test_terminal_jobs_reject_every_transition(terminal: JobStatus, target: JobStatus) -> None:
    with pytest.raises(InvalidJobTransitionError) as raised:
        validate_transition(terminal, target)

    assert raised.value.current is terminal
    assert raised.value.target is target


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (JobStatus.QUEUED, JobStatus.SUCCEEDED),
        (JobStatus.RUNNING, JobStatus.QUEUED),
        (JobStatus.CANCEL_REQUESTED, JobStatus.SUCCEEDED),
        (JobStatus.FAILED, JobStatus.RUNNING),
    ],
)
def test_invalid_active_transitions_are_rejected(current: JobStatus, target: JobStatus) -> None:
    with pytest.raises(InvalidJobTransitionError):
        validate_transition(current, target)
