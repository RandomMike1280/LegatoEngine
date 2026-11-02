"""The BS-RoFormer source separation model (band-split RoFormer), vendored from ZFTurbo's
Music-Source-Separation-Training (MIT). separate.py loads the BS-RoFormer-SW 6-stem weights into it."""

from .bs_roformer import BSRoformer

__all__ = ["BSRoformer"]
