"""Unit tests for GeminiClient and structured AI schema validation."""

import json
import pytest
import requests
from pydantic import BaseModel
from jobradar.domain.models import AICopilotInsight, ExtractedJobItem
from jobradar.services.ai_client import GeminiClient


class SimpleTestSchema(BaseModel):
    name: str
    score: int


def test_gemini_client_is_configured():
    # Unconfigured cases
    assert GeminiClient(api_key=None).is_configured() is False
    assert GeminiClient(api_key="").is_configured() is False
    assert GeminiClient(api_key="your_gemini_api_key_here").is_configured() is False
    assert GeminiClient(api_key="change_me").is_configured() is False

    # Valid key
    assert GeminiClient(api_key="AIzaSyValidGeminiKey123").is_configured() is True


def test_gemini_client_generate_text_success(mocker):
    client = GeminiClient(api_key="AIzaSyValidGeminiKey123")

    mock_resp = mocker.MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "This is a detailed analysis of the job fit."}]
                }
            }
        ]
    }
    mocker.patch.object(client.session, "post", return_value=mock_resp)

    text = client.generate_text(prompt="Analyze this job")
    assert text == "This is a detailed analysis of the job fit."


def test_gemini_client_generate_json_with_pydantic_schema(mocker):
    client = GeminiClient(api_key="AIzaSyValidGeminiKey123")

    payload_json = {
        "semantic_fit_score": 95,
        "fit_rationale": "Strong alignment with candidate's Python and data pipeline experience.",
        "key_strengths": ["Python", "FastAPI", "PostgreSQL", "Kafka"],
        "skill_gaps": ["Docker Swarm"],
        "tailored_pitch": "Engineered automated ETL pipelines matching Co-op Bank's streaming requirements.",
    }

    mock_resp = mocker.MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": json.dumps(payload_json)}]
                }
            }
        ]
    }
    mocker.patch.object(client.session, "post", return_value=mock_resp)

    insight = client.generate_json(
        prompt="Evaluate candidate against job",
        schema_cls=AICopilotInsight,
    )

    assert isinstance(insight, AICopilotInsight)
    assert insight.semantic_fit_score == 95
    assert "Python" in insight.key_strengths
    assert "Docker Swarm" in insight.skill_gaps


def test_gemini_client_unconfigured_returns_none():
    client = GeminiClient(api_key=None)
    assert client.generate_text("Prompt") is None
    assert client.generate_json("Prompt", schema_cls=SimpleTestSchema) is None


def test_gemini_client_network_error_handles_gracefully(mocker):
    client = GeminiClient(api_key="AIzaSyValidGeminiKey123")
    mocker.patch.object(
        client.session,
        "post",
        side_effect=requests.exceptions.ConnectTimeout("Connection timed out"),
    )

    # Should log error and return None rather than raising an unhandled exception
    res_text = client.generate_text("Test prompt")
    assert res_text is None

    res_json = client.generate_json("Test prompt", schema_cls=SimpleTestSchema)
    assert res_json is None
