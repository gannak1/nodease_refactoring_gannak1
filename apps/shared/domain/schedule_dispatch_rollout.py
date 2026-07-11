from __future__ import annotations

import argparse
from dataclasses import dataclass


class ScheduleDispatchRolloutError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ScheduleDispatchRolloutState:
    fingerprint: str
    image: str


def evaluate_schedule_dispatch_rollout(
    *,
    desired_fingerprint: str,
    previous_fingerprint: str,
    desired_gateway_image: str,
    desired_worker_image: str,
    gateway: ScheduleDispatchRolloutState | None,
    worker: ScheduleDispatchRolloutState | None,
) -> str:
    """Return all/gateway/worker/none for a fail-closed staged rollout."""
    if not desired_fingerprint or not previous_fingerprint:
        raise ScheduleDispatchRolloutError("rollout fingerprints are required")
    target_mode = _mode(desired_fingerprint)

    if gateway is None or worker is None:
        if target_mode != "disabled":
            raise ScheduleDispatchRolloutError(
                "non-disabled rollout requires both live deployments"
            )
        existing = gateway or worker
        if existing and existing.fingerprint not in {
            desired_fingerprint,
            previous_fingerprint,
        }:
            raise ScheduleDispatchRolloutError(
                "bootstrap deployment fingerprint is not recognized"
            )
        return "all"

    if gateway.fingerprint == worker.fingerprint == desired_fingerprint:
        if (
            gateway.image == desired_gateway_image
            and worker.image == desired_worker_image
        ):
            return "none"
        return "all"

    if gateway.fingerprint == worker.fingerprint:
        if gateway.fingerprint != previous_fingerprint:
            raise ScheduleDispatchRolloutError(
                "live fingerprint does not match the approved previous value"
            )
        if _mode(previous_fingerprint) == "claim" and target_mode == "claim":
            raise ScheduleDispatchRolloutError(
                "drain mode is required before changing active claim settings"
            )
        return "all"

    if target_mode == "claim":
        if (
            worker.fingerprint == desired_fingerprint
            and worker.image == desired_worker_image
            and gateway.fingerprint == previous_fingerprint
        ):
            return "gateway"
    elif (
        gateway.fingerprint == desired_fingerprint
        and gateway.image == desired_gateway_image
        and worker.fingerprint == previous_fingerprint
    ):
        return "worker"

    raise ScheduleDispatchRolloutError(
        "live fingerprints do not match a resumable staged rollout"
    )


def _mode(fingerprint: str) -> str:
    parts = fingerprint.split("|")
    if len(parts) < 3 or parts[0] != "v1" or parts[1] not in {
        "disabled",
        "drain",
        "claim",
    }:
        raise ScheduleDispatchRolloutError("invalid schedule dispatch fingerprint")
    return parts[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--desired", required=True)
    parser.add_argument("--previous", required=True)
    parser.add_argument("--desired-gateway-image", required=True)
    parser.add_argument("--desired-worker-image", required=True)
    parser.add_argument("--gateway-fingerprint", default="")
    parser.add_argument("--gateway-image", default="")
    parser.add_argument("--worker-fingerprint", default="")
    parser.add_argument("--worker-image", default="")
    args = parser.parse_args()
    try:
        action = evaluate_schedule_dispatch_rollout(
            desired_fingerprint=args.desired,
            previous_fingerprint=args.previous,
            desired_gateway_image=args.desired_gateway_image,
            desired_worker_image=args.desired_worker_image,
            gateway=(
                ScheduleDispatchRolloutState(
                    fingerprint=args.gateway_fingerprint,
                    image=args.gateway_image,
                )
                if args.gateway_fingerprint
                else None
            ),
            worker=(
                ScheduleDispatchRolloutState(
                    fingerprint=args.worker_fingerprint,
                    image=args.worker_image,
                )
                if args.worker_fingerprint
                else None
            ),
        )
    except ScheduleDispatchRolloutError:
        print("schedule dispatch rollout state is not safe")
        return 1
    print(action)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
