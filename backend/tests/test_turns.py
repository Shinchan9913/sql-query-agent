import asyncio

from app.api.turns import TurnManager


async def _events(n, delay=0.01):
    for i in range(n):
        await asyncio.sleep(delay)
        yield f"e{i}"


async def _collect(turn):
    return [e async for e in turn.subscribe()]


def test_late_subscriber_gets_full_replay():
    async def main():
        manager = TurnManager()
        turn = manager.start("t", _events(5), on_cancel=None)
        await asyncio.sleep(0.03)
        return await _collect(turn), manager.get("t")

    events, after = asyncio.run(main())
    assert events == ["e0", "e1", "e2", "e3", "e4"]
    assert after is None  # dropped once finished


def test_turn_survives_subscriber_leaving():
    async def main():
        manager = TurnManager()
        turn = manager.start("t", _events(5), on_cancel=None)
        async for _ in turn.subscribe():
            break  # client disconnects after the first event
        await turn.task
        return turn.events

    assert asyncio.run(main()) == ["e0", "e1", "e2", "e3", "e4"]


def test_one_turn_per_thread_and_cancel():
    async def main():
        manager = TurnManager()
        stopped = []

        async def on_cancel():
            stopped.append(True)
            return "stopped"

        turn = manager.start("t", _events(100), on_cancel)
        try:
            manager.start("t", _events(1), on_cancel)
            raise AssertionError("second turn should be refused")
        except Exception as e:
            assert type(e).__name__ == "TurnInProgressError"
        await asyncio.sleep(0.03)
        assert manager.cancel("t")
        events = await _collect(turn)
        return events, stopped, manager.get("t")

    events, stopped, after = asyncio.run(main())
    assert events[-1] == "stopped" and stopped == [True] and after is None
