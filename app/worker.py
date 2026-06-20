from __future__ import annotations

import argparse
import asyncio
import signal
from typing import Any

import structlog

from app.db.engine import session_scope
from app.db.queries import resources as res_q
from app.logging import setup as setup_logging
from app.runtime.work_queue import execute_work_item, is_work_ready_for_execution

logger = structlog.get_logger()


async def run_worker(
    *,
    environment_id: str | None,
    poll_interval_seconds: float,
    once: bool,
) -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    while not stop_event.is_set():
        work = await _next_runnable_work(environment_id=environment_id)
        if work is None:
            if once:
                return
            await asyncio.sleep(poll_interval_seconds)
            continue
        logger.info("worker_executing_work", work_id=work["id"], session_id=work.get("session_id"))
        await execute_work_item(work["id"])
        if once:
            return


async def _next_runnable_work(*, environment_id: str | None) -> dict[str, Any] | None:
    async with session_scope() as db:
        if environment_id is not None:
            candidates = await res_q.list_resources(
                db,
                resource_type="environment_work",
                parent_id=environment_id,
                limit=1000,
            )
        else:
            candidates = await res_q.list_resources(db, resource_type="environment_work", limit=1000)
        runnable = [work for work in reversed(candidates) if is_work_ready_for_execution(work)]
        if not runnable:
            return None
        work = runnable[0]
        return {"id": work.id, **(work.data or {})}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Open Managed Agents Postgres queue worker.")
    parser.add_argument("--environment-id", default=None)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    setup_logging(app_env="worker", sentry_dsn="", log_level="INFO")
    asyncio.run(
        run_worker(
            environment_id=args.environment_id,
            poll_interval_seconds=args.poll_interval,
            once=args.once,
        )
    )


if __name__ == "__main__":
    main()
