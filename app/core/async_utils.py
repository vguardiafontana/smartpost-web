from __future__ import annotations

import asyncio


async def ordered_map(values, callback, concurrency=3):
    """Bound read requests while preserving input order and per-item failures."""
    semaphore = asyncio.Semaphore(concurrency)

    async def one(value):
        async with semaphore:
            return await callback(value)

    return await asyncio.gather(*(one(value) for value in values), return_exceptions=True)
