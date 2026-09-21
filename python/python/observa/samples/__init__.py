"""Bundled strategy samples and demo datasets.

* :class:`EmaCrossover` — the strategy used by the real EUR/USD demo.
* :class:`~observa.samples.sample_strategy.SampleEma` — the strategy used by the
  deterministic synthetic quickstart.

The demo dataset itself is accessed with :func:`observa.demo_data_path`.
"""

from .demo_strategy import EmaCrossover

__all__ = ["EmaCrossover"]
