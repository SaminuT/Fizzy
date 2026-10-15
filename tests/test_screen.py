import pytest

from fizzy.ai.base import Image
from fizzy.context.screen import Monitor, Shot, match_screens


def test_mixed_dpi_with_qt_keeping_origins():
    mons = match_screens(
        [(0, 0, 2560, 1440), (2560, 0, 1920, 1080)],
        [((0, 0, 1707, 960), 1.5), ((2560, 0, 1920, 1080), 1.0)],
    )
    assert [(m.scale, m.logical_left) for m in mons] == [(1.5, 0.0), (1.0, 2560.0)]


def test_mixed_dpi_with_qt_scaling_origins_and_other_order():
    mons = match_screens(
        [(0, 0, 2560, 1440), (2560, 0, 1920, 1080)],
        [((1707, 0, 1920, 1080), 1.0), ((0, 0, 1707, 960), 1.5)],
    )
    assert mons[0].scale == 1.5
    assert mons[1].logical_left == 1707.0


def test_unmatched_monitor_assumes_no_scaling():
    (m,) = match_screens([(0, 0, 800, 600)], [])
    assert m.scale == 1.0 and m.logical_left == 0.0


def test_logical_physical_round_trip():
    m = Monitor(2, 2560, 0, 1920, 1080, 1707.0, 0.0, 1.25)
    lx, ly = m.to_logical(2560 + 500, 400)
    assert (lx, ly) == (1707 + 400, 320)
    assert m.to_physical(lx, ly) == pytest.approx((3060, 400))


def test_shot_norm_and_image_mapping():
    m = Monitor(1, 0, 0, 2000, 1000, 0, 0, 1.0)
    shot = Shot(m, Image("", 1000, 500), None)
    assert shot.norm_to_physical(500, 500) == (1000, 500)
    assert shot.physical_to_norm(1000, 500) == (500, 500)
    assert shot.image_to_physical(100, 50) == (200, 100)
