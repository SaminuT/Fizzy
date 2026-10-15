"""Decide when the user has finished speaking, from the mic level alone.

The threshold adapts to the room. The first few frames, before anyone
starts talking, give a first guess at the background noise; after that the
estimate follows quiet moments quickly and creeps up slowly under steady
noise (a fan, traffic), so constant noise is never mistaken for an endless
sentence.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EndpointConfig:
    min_threshold: float = 0.008    # absolute floor for "speech"
    noise_margin: float = 3.0       # speech must be this many times the noise floor
    end_silence_s: float = 1.0      # quiet this long after speech = finished
    no_speech_s: float = 6.0        # nothing said at all = give up
    max_s: float = 60.0             # hard cap
    min_speech_s: float = 0.15      # shorter bursts are clicks, not words
    calibrate_s: float = 0.12       # frames used for the first noise guess


class Endpointer:
    def __init__(self, cfg: EndpointConfig | None = None):
        self.cfg = cfg or EndpointConfig()
        self.noise = self.cfg.min_threshold / self.cfg.noise_margin
        self.elapsed = 0.0
        self.speech_s = 0.0
        self.quiet_s = 0.0
        self.reason = ""
        self._calibration: list[float] = []

    @property
    def heard_speech(self) -> bool:
        return self.speech_s >= self.cfg.min_speech_s

    def threshold(self) -> float:
        return max(self.cfg.min_threshold, self.noise * self.cfg.noise_margin)

    def feed(self, level: float, dt: float) -> bool:
        """Add one frame's level. True once the utterance is over."""
        self.elapsed += dt
        if self.elapsed <= self.cfg.calibrate_s:
            self._calibration.append(level)
            self.noise = max(self.noise, min(0.05, sum(self._calibration) / len(self._calibration)))
            return False
        self._track_noise(level)
        if level > self.threshold():
            self.speech_s += dt
            self.quiet_s = 0.0
        else:
            self.quiet_s += dt

        if self.elapsed >= self.cfg.max_s:
            self.reason = "max"
            return True
        if self.heard_speech and self.quiet_s >= self.cfg.end_silence_s:
            self.reason = "silence"
            return True
        if not self.heard_speech and self.elapsed >= self.cfg.no_speech_s:
            self.reason = "no-speech"
            return True
        return False

    def _track_noise(self, level: float) -> None:
        if level < self.noise:
            self.noise += (level - self.noise) * 0.1        # quiet: follow down quickly
        else:
            self.noise += (level - self.noise) * 0.004      # loud: rise slowly (speech is brief, noise isn't)
