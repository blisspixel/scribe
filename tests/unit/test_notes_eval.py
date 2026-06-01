"""Unit tests for the notes provider comparison / eval framework."""

import json

from scribe.utils import notes_eval
from scribe.utils.notes_eval import (
    EvalResult,
    format_scorecard,
    objective_struct_score,
    parse_provider_spec,
    run_notes_eval,
)

_FULL = json.dumps(
    {
        "decisions": ["ship v2 Monday"],
        "action_items": ["Bob runs migration"],
        "key_claims": ["backend is done"],
        "blockers": ["flaky CI"],
        "next_steps": ["finish reporting page"],
    }
)


class TestParseProviderSpec:
    def test_provider_only(self):
        assert parse_provider_spec("openai") == ("openai", None)

    def test_provider_and_simple_model(self):
        assert parse_provider_spec("openai:gpt-5.4") == ("openai", "gpt-5.4")

    def test_ollama_model_with_colon_preserved(self):
        # Only the first colon splits; the tag keeps its own colon.
        assert parse_provider_spec("ollama:qwen2.5:14b") == ("ollama", "qwen2.5:14b")

    def test_strips_and_lowercases_provider(self):
        assert parse_provider_spec("  OpenAI  ") == ("openai", None)


class TestObjectiveStructScore:
    def test_full_valid_is_100(self):
        score, detail = objective_struct_score(_FULL)
        assert score == 100.0
        assert detail["json_valid"] is True
        assert detail["total_items"] == 5

    def test_invalid_json_is_zero(self):
        score, detail = objective_struct_score("not json at all")
        assert score == 0.0
        assert detail["json_valid"] is False

    def test_json_embedded_in_prose_is_recovered(self):
        score, _ = objective_struct_score(f"Here are the notes:\n{_FULL}\nThanks!")
        assert score == 100.0

    def test_missing_sections_scores_lower(self):
        partial = json.dumps({"decisions": ["x"], "action_items": [], "key_claims": ["y"]})
        score, detail = objective_struct_score(partial)
        # 3 of 5 present, 2 of 5 non-empty -> 40 + 30*0.6 + 30*0.4 = 70.0
        assert score == 70.0
        assert detail["json_valid"] is True

    def test_empty_object_gets_validity_only(self):
        score, _ = objective_struct_score("{}")
        assert score == 40.0

    def test_think_block_is_stripped(self):
        # Reasoning models (e.g. some Gemma/Qwen builds) emit <think> with braces
        # that would otherwise break greedy JSON extraction.
        noisy = f"<think>maybe {{a:1}} hmm</think>\n```json\n{_FULL}\n```"
        score, detail = objective_struct_score(noisy)
        assert score == 100.0
        assert detail["json_valid"] is True

    def test_fenced_json_is_recovered(self):
        score, _ = objective_struct_score(f"```json\n{_FULL}\n```")
        assert score == 100.0


class TestGenerateAndRun:
    class _FakeProvider:
        def __init__(self, model: str, content: str):
            self.config = type("C", (), {"model": model})()
            self._content = content

        def chat_completion_with_json(self, messages, json_schema=None, **kwargs):
            return {
                "content": self._content,
                "usage": {"total_tokens": 42, "cost_usd": 0.0, "cost_source": "local"},
            }

    def _patch_provider(self, monkeypatch, content: str = _FULL, model: str = "qwen2.5:14b"):
        def fake_get_provider(feature, provider_name=None, model=None):
            resolved = model or "qwen2.5:14b"
            return TestGenerateAndRun._FakeProvider(resolved, content)

        monkeypatch.setattr(notes_eval, "get_provider", fake_get_provider)

    def test_run_objective_only(self, monkeypatch):
        self._patch_provider(monkeypatch)
        results = run_notes_eval("transcript", ["ollama:qwen2.5:14b"], judge_spec=None)
        assert len(results) == 1
        r = results[0]
        assert r.ok is True
        assert r.struct_score == 100.0
        assert r.cost_usd == 0.0
        assert r.cost_source == "local"
        assert r.judge_score is None

    def test_generation_error_is_captured(self, monkeypatch):
        def boom(feature, provider_name=None, model=None):
            raise RuntimeError("server down")

        monkeypatch.setattr(notes_eval, "get_provider", boom)
        results = run_notes_eval("t", ["ollama:x"], judge_spec=None)
        assert results[0].ok is False
        assert "server down" in (results[0].error or "")

    def test_judge_adds_score(self, monkeypatch):
        judge_payload = json.dumps(
            {"scores": [{"candidate": 1, "coverage": 9, "faithfulness": 8, "structure": 10}]}
        )

        def fake_get_provider(feature, provider_name=None, model=None):
            # The judge call carries the judge payload; generation carries notes.
            content = judge_payload if provider_name == "openai" else _FULL
            return TestGenerateAndRun._FakeProvider(model or "m", content)

        monkeypatch.setattr(notes_eval, "get_provider", fake_get_provider)
        results = run_notes_eval("t", ["ollama:qwen2.5:14b"], judge_spec="openai")
        assert results[0].judge_score == 9.0  # (9+8+10)/3 = 9.0
        assert results[0].judge_detail is not None


class TestFormatScorecard:
    def test_includes_judge_column_when_present(self):
        results = [
            EvalResult(
                spec="ollama:q",
                provider="ollama",
                model="q",
                ok=True,
                latency_sec=1.0,
                cost_usd=0.0,
                cost_source="local",
                struct_score=92.0,
                judge_score=7.8,
            )
        ]
        out = format_scorecard(results)
        assert "judge" in out
        assert "$0.00" in out
        assert "92.0%" in out

    def test_objective_only_has_no_judge_column(self):
        results = [
            EvalResult(
                spec="openai",
                provider="openai",
                model="gpt-5.5",
                ok=True,
                latency_sec=2.0,
                cost_usd=0.012,
                cost_source="local_estimate",
                struct_score=100.0,
            )
        ]
        out = format_scorecard(results)
        assert "judge" not in out
        assert "$0.0120" in out
