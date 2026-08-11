from __future__ import annotations

import asyncio

import pytest

from app.infrastructure.lock.in_memory_lock import InMemorySessionLock


@pytest.mark.asyncio
async def test_acquire_then_release():
    lock = InMemorySessionLock(timeout_sec=60)
    r = await lock.acquire("pc-a")
    assert r.locked and r.client == "pc-a"
    u = await lock.release("pc-a")
    assert u.unlocked
    r2 = await lock.acquire("pc-b")
    assert r2.locked and r2.client == "pc-b"


@pytest.mark.asyncio
async def test_acquire_busy_returns_holder():
    lock = InMemorySessionLock(timeout_sec=60)
    await lock.acquire("pc-a")
    r = await lock.acquire("pc-b")
    assert not r.locked
    assert r.holder == "pc-a"
    assert r.remaining_sec > 0


@pytest.mark.asyncio
async def test_same_holder_renews():
    lock = InMemorySessionLock(timeout_sec=60)
    await lock.acquire("pc-a")
    r = await lock.acquire("pc-a")
    assert r.locked and r.renewed


@pytest.mark.asyncio
async def test_timeout_expires_holder():
    lock = InMemorySessionLock(timeout_sec=1)
    await lock.acquire("pc-a")
    await asyncio.sleep(1.1)
    # Expired -> a different client can take over
    r = await lock.acquire("pc-b")
    assert r.locked and r.client == "pc-b"


@pytest.mark.asyncio
async def test_release_wrong_client_noop():
    lock = InMemorySessionLock(timeout_sec=60)
    await lock.acquire("pc-a")
    u = await lock.release("pc-b")
    assert not u.unlocked
    assert u.holder == "pc-a"


@pytest.mark.asyncio
async def test_status_reflects_state():
    lock = InMemorySessionLock(timeout_sec=60)
    s = await lock.status()
    assert not s.locked
    await lock.acquire("pc-a")
    s = await lock.status()
    assert s.locked and s.holder == "pc-a"
