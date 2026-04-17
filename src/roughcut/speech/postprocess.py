from __future__ import annotations

from . import subtitle_segmentation as _subtitle_segmentation

for _name in dir(_subtitle_segmentation):
    if _name.startswith("__"):
        continue
    globals()[_name] = getattr(_subtitle_segmentation, _name)

