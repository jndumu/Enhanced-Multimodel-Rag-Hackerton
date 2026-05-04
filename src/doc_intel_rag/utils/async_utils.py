"""Async utility helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


async def run_in_executor(func: Any, *args: Any) -> Any:
    """Run a blocking function in the default thread pool executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, func, *args)


async def gather_with_concurrency(n: int, *coros: Coroutine[Any, Any, T]) -> list[T]:
    """Run coroutines with a bounded concurrency semaphore."""
    semaphore = asyncio.Semaphore(n)

    async def _sem_coro(coro: Coroutine[Any, Any, T]) -> T:
        async with semaphore:
            return await coro

    return list(await asyncio.gather(*(_sem_coro(c) for c in coros)))
