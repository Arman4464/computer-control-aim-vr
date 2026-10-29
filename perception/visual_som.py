"""
Compatibility bridge for VisualSOM and OmniParser V2.
Re-exports unified canonical implementations from perception.som_engine.
"""

from perception.som_engine import (
    calculate_iou,
    calculate_containment,
    _calculate_iou,
    _calculate_containment,
    apply_non_maximum_suppression,
    LocalIconDetector,
    VisualSOM,
    SoMEngine,
    default_som,
    MarkResult,
)

__all__ = [
    "calculate_iou",
    "calculate_containment",
    "_calculate_iou",
    "_calculate_containment",
    "apply_non_maximum_suppression",
    "LocalIconDetector",
    "VisualSOM",
    "SoMEngine",
    "default_som",
    "MarkResult",
]