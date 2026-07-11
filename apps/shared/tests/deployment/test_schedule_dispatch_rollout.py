import pytest
from apps.shared.domain.schedule_dispatch_rollout import (
    ScheduleDispatchRolloutError,
    ScheduleDispatchRolloutState,
    evaluate_schedule_dispatch_rollout,
)

DISABLED = "v1|disabled|5"
DRAIN = "v1|drain|5"
CLAIM = "v1|claim|5"
GATEWAY_IMAGE = "registry/gateway:commit"
WORKER_IMAGE = "registry/worker:commit"


def _state(fingerprint, image):
    return ScheduleDispatchRolloutState(fingerprint=fingerprint, image=image)


@pytest.mark.parametrize(
    ("desired", "previous", "gateway", "worker", "expected"),
    [
        (DISABLED, DISABLED, None, None, "all"),
        (
            CLAIM,
            DRAIN,
            _state(DRAIN, "registry/gateway:old"),
            _state(DRAIN, "registry/worker:old"),
            "all",
        ),
        (
            CLAIM,
            DRAIN,
            _state(DRAIN, "registry/gateway:old"),
            _state(CLAIM, WORKER_IMAGE),
            "gateway",
        ),
        (
            DRAIN,
            CLAIM,
            _state(DRAIN, GATEWAY_IMAGE),
            _state(CLAIM, "registry/worker:old"),
            "worker",
        ),
        (
            CLAIM,
            DRAIN,
            _state(CLAIM, GATEWAY_IMAGE),
            _state(CLAIM, WORKER_IMAGE),
            "none",
        ),
        (
            CLAIM,
            CLAIM,
            _state(CLAIM, "registry/gateway:old"),
            _state(CLAIM, WORKER_IMAGE),
            "all",
        ),
    ],
)
def test_rollout_state_matrix(desired, previous, gateway, worker, expected):
    assert (
        evaluate_schedule_dispatch_rollout(
            desired_fingerprint=desired,
            previous_fingerprint=previous,
            desired_gateway_image=GATEWAY_IMAGE,
            desired_worker_image=WORKER_IMAGE,
            gateway=gateway,
            worker=worker,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("desired", "previous", "gateway", "worker"),
    [
        (CLAIM, DRAIN, None, None),
        (
            CLAIM,
            DRAIN,
            _state(DRAIN, "registry/gateway:old"),
            _state(CLAIM, "registry/worker:wrong"),
        ),
        (
            DRAIN,
            CLAIM,
            _state(CLAIM, "registry/gateway:old"),
            _state(DRAIN, WORKER_IMAGE),
        ),
        (
            CLAIM,
            DRAIN,
            _state("v1|disabled|5", "registry/gateway:old"),
            _state("v1|disabled|5", "registry/worker:old"),
        ),
        (
            "v1|claim|6",
            CLAIM,
            _state(CLAIM, "registry/gateway:old"),
            _state(CLAIM, "registry/worker:old"),
        ),
        (
            DISABLED,
            CLAIM,
            _state(CLAIM, "registry/gateway:old"),
            _state(CLAIM, "registry/worker:old"),
        ),
        (
            "v1|claim|6",
            CLAIM,
            _state("v1|claim|6", GATEWAY_IMAGE),
            _state("v1|claim|6", WORKER_IMAGE),
        ),
        (
            CLAIM,
            DRAIN,
            _state(CLAIM, "registry/gateway:old"),
            _state(CLAIM, WORKER_IMAGE),
        ),
    ],
)
def test_rollout_state_rejects_non_resumable_mismatch(
    desired, previous, gateway, worker
):
    with pytest.raises(ScheduleDispatchRolloutError):
        evaluate_schedule_dispatch_rollout(
            desired_fingerprint=desired,
            previous_fingerprint=previous,
            desired_gateway_image=GATEWAY_IMAGE,
            desired_worker_image=WORKER_IMAGE,
            gateway=gateway,
            worker=worker,
        )
