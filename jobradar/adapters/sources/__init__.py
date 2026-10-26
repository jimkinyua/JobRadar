"""Source adapters package."""
from jobradar.adapters.sources.base import BaseSourceAdapter
from jobradar.adapters.sources.factory import get_source_adapter
from jobradar.adapters.sources.ats_sniffer import detect_ats_employer

__all__ = ["BaseSourceAdapter", "get_source_adapter", "detect_ats_employer"]
