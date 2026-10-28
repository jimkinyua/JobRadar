"""
Lightweight, resilient Google Gemini Client for JobRadar.

Interacts with the Google Gemini API (Gemini 2.0 Flash) via REST.
Supports schema-constrained JSON generation, Pydantic model validation,
and graceful fallbacks.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional, Type, TypeVar
import requests
from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiClient:
    """Production-grade client for Google Gemini 2.0 Flash."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-2.0-flash",
        timeout: float = 30.0,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model = model
        self.timeout = timeout
        self.session = session or requests.Session()

    def is_configured(self) -> bool:
        """Check whether a valid Gemini API key is present."""
        if not self.api_key:
            return False
        if self.api_key in ("your_gemini_api_key_here", "change_me", "none", ""):
            return False
        return True

    def generate_text(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
    ) -> Optional[str]:
        """
        Generate raw text response from Gemini.

        Note on temperature (0.2):
        Low temperature prioritizes factuality and determinism over creativity,
        minimizing hallucinations during technical role and fit evaluations.
        """
        if not self.is_configured():
            logger.debug("GeminiClient called but GEMINI_API_KEY is not configured.")
            return None

        url = f"{GEMINI_API_BASE}/{self.model}:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}

        payload: dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature},
        }

        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        try:
            resp = self.session.post(url, headers=headers, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()

            candidates = data.get("candidates") or []
            if not candidates:
                logger.warning("Gemini returned 0 candidates in response: %s", data)
                return None

            content = candidates[0].get("content") or {}
            parts = content.get("parts") or []
            if not parts:
                return None

            return parts[0].get("text", "").strip()

        except requests.exceptions.RequestException as e:
            logger.error("Gemini API request failed: %s", e)
            return None
        except Exception as e:
            logger.error("Unexpected error in Gemini generate_text: %s", e)
            return None

    def generate_json(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        schema_cls: Optional[Type[T]] = None,
        temperature: float = 0.1,
    ) -> Any:
        """
        Generate structured JSON from Gemini.
        If schema_cls is provided, validates and parses directly into a Pydantic model instance.

        Note on temperature (0.1):
        Low temperature guarantees rigid JSON syntax adherence, consistent field naming,
        and prevents hallucinations when extracting unstructured HTML entities.
        """
        if not self.is_configured():
            logger.debug("GeminiClient called for JSON generation but GEMINI_API_KEY is not configured.")
            return None

        url = f"{GEMINI_API_BASE}/{self.model}:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}

        gen_config: dict[str, Any] = {
            "temperature": temperature,
            "responseMimeType": "application/json",
        }

        payload: dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": gen_config,
        }

        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        try:
            resp = self.session.post(url, headers=headers, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()

            candidates = data.get("candidates") or []
            if not candidates:
                logger.warning("Gemini returned 0 candidates for JSON generation: %s", data)
                return None

            content = candidates[0].get("content") or {}
            parts = content.get("parts") or []
            if not parts:
                return None

            raw_text = parts[0].get("text", "").strip()
            if not raw_text:
                return None

            if schema_cls and issubclass(schema_cls, BaseModel):
                return schema_cls.model_validate_json(raw_text)

            return json.loads(raw_text)

        except requests.exceptions.RequestException as e:
            logger.error("Gemini API JSON request failed: %s", e)
            return None
        except json.JSONDecodeError as e:
            logger.error("Failed to decode JSON from Gemini output: %s", e)
            return None
        except Exception as e:
            logger.error("Unexpected error in Gemini generate_json: %s", e)
            return None
