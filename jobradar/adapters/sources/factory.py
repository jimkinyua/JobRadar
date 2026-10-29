"""Factory returning the appropriate SourceAdapter based on source type."""

from __future__ import annotations

from jobradar.config import SourceConfig, CrawlerConfig
from jobradar.adapters.sources.base import BaseSourceAdapter
from jobradar.adapters.sources.smartrecruiters import SmartRecruitersSourceAdapter
from jobradar.adapters.sources.greenhouse import GreenhouseSourceAdapter
from jobradar.adapters.sources.lever import LeverSourceAdapter
from jobradar.adapters.sources.workable import WorkableSourceAdapter
from jobradar.adapters.sources.remotive import RemotiveSourceAdapter
from jobradar.adapters.sources.reliefweb import ReliefWebSourceAdapter
from jobradar.adapters.sources.rss import RssSourceAdapter
from jobradar.adapters.sources.html import HtmlSourceAdapter
from jobradar.adapters.sources.workday import WorkdaySourceAdapter
from jobradar.adapters.sources.ai_html import AiHtmlSourceAdapter


def get_source_adapter(source_config: SourceConfig, crawler_config: CrawlerConfig) -> BaseSourceAdapter:
    """Instantiate a source adapter for the given configuration."""
    source_type = source_config.type.lower().strip()

    if source_type == "smartrecruiters":
        return SmartRecruitersSourceAdapter(source_config, crawler_config)
    elif source_type == "greenhouse":
        return GreenhouseSourceAdapter(source_config, crawler_config)
    elif source_type == "lever":
        return LeverSourceAdapter(source_config, crawler_config)
    elif source_type == "workable":
        return WorkableSourceAdapter(source_config, crawler_config)
    elif source_type == "remotive":
        return RemotiveSourceAdapter(source_config, crawler_config)
    elif source_type == "reliefweb":
        return ReliefWebSourceAdapter(source_config, crawler_config)
    elif source_type == "rss":
        return RssSourceAdapter(source_config, crawler_config)
    elif source_type == "html":
        return HtmlSourceAdapter(source_config, crawler_config)
    elif source_type in ("ai_html", "ai"):
        return AiHtmlSourceAdapter(source_config, crawler_config)
    elif source_type == "workday":
        return WorkdaySourceAdapter(source_config, crawler_config)
    else:
        raise ValueError(f"Unknown or unsupported source type: '{source_type}' for source '{source_config.id}'")
