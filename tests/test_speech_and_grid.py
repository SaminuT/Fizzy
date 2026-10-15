from fizzy.pointing.grid import Box, cell_name, parse_cell
from fizzy.speech.endpoint import EndpointConfig, Endpointer

DT = 0.03


def run(levels, cfg=None):
    ep = Endpointer(cfg)
    for i, level in enumerate(levels):
        if ep.feed(level, DT):
            return i, ep.reason
    return None, ""


def test_ends_after_speech_then_silence():
    i, reason = run([0.002] * 20 + [0.05] * 30 + [0.003] * 60)
    assert reason == "silence"
    assert 80 <= i <= 90            # ~1 s of quiet after the speech


def test_gives_up_without_speech():
    _, reason = run([0.003] * 400)
    assert reason == "no-speech"


def test_click_is_not_speech():
    _, reason = run([0.003] * 10 + [0.2] * 2 + [0.003] * 400)
    assert reason == "no-speech"


def test_noisy_room_still_ends():
    # A loud fan from the start, a sentence well above it, then just the fan again.
    i, reason = run([0.03] * 30 + [0.2] * 60 + [0.03] * 200)
    assert reason == "silence"
    assert i < 140                  # not stuck until the 60 s cap


def test_noise_that_starts_mid_recording_doesnt_record_forever():
    _, reason = run([0.002] * 10 + [0.05] * 30 + [0.025] * 3000)
    assert reason in ("silence", "no-speech")


def test_hard_cap():
    _, reason = run([0.1] * 100, EndpointConfig(max_s=1.0))
    assert reason == "max"


def test_cells():
    assert cell_name(0, 0) == "A1" and cell_name(9, 5) == "J6"
    assert parse_cell("It's in D4.", 10, 6) == (3, 3)
    assert parse_cell("NONE", 10, 6) is None
    assert parse_cell("K9", 10, 6) is None


def test_box_zoom_maths():
    whole = Box(0, 0, 1000, 600)
    cell = whole.cell(10, 6, 0, 0).grown(0.5, whole)     # clipped at the corner
    assert (cell.left, cell.top, cell.width, cell.height) == (0, 0, 150, 150)
    assert whole.cell(10, 6, 3, 2).centre == (350, 250)
