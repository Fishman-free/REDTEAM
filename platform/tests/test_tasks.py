"""Deterministic owner-task generation bounds and reproducibility."""

import pytest

from redteam_platform.byoa.tasks import TaskGenerator


def test_generation_is_seeded_and_bounded():
    first = TaskGenerator(
        seed="contest-seed",
        contest_end=10_000,
        now=1_000,
        min_amount=10,
        max_amount=100,
    ).generate(5)
    second = TaskGenerator(
        seed="contest-seed",
        contest_end=10_000,
        now=1_000,
        min_amount=10,
        max_amount=100,
    ).generate(5)

    assert [item.text for item in first] == [item.text for item in second]
    for item in first:
        assert 10 <= item.amount <= 100
        assert 1_000 < item.deadline <= 10_000
        assert "INV-" in item.text
        assert item.label


def test_generation_rejects_invalid_bounds():
    with pytest.raises(ValueError):
        TaskGenerator(seed="x", contest_end=100, now=100, min_amount=1, max_amount=2)
    with pytest.raises(ValueError):
        TaskGenerator(seed="", contest_end=1000, now=1, min_amount=1, max_amount=2)
    generator = TaskGenerator(
        seed="x", contest_end=10_000, now=1_000, min_amount=1, max_amount=2
    )
    with pytest.raises(ValueError):
        generator.generate(0)
