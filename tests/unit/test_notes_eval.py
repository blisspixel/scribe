"""Unit tests for the notes provider comparison / eval framework."""

import json

from scribe.utils import notes_eval
from scribe.utils.notes_eval import (
    EvalResult,
    ProviderAvailability,
    format_scorecard,
    objective_struct_score,
    parse_provider_spec,
    resolve_compare_plan,
    run_notes_eval,
    summarize_verdict,
)


def _avail(cloud=None, models=None, auto=None) -> ProviderAvailability:
    return ProviderAvailability(cloud=cloud or [], ollama_models=models or [], ollama_auto=auto)


def _result(provider, model, struct, judge=None, cost=None, ok=True) -> EvalResult:
    return EvalResult(
        spec=f"{provider}:{model}",
        provider=provider,
        model=model,
        ok=ok,
        latency_sec=1.0,
        cost_usd=cost,
        cost_source="local" if provider == "ollama" else "local_estimate",
        struct_score=struct,
        judge_score=judge,
    )


_FULL = json.dumps(
    {
        "decisions": ["ship v2 Monday"],
        "action_items": ["Backend lead runs migration"],
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
        assert score == 60.0
        assert detail["json_valid"] is True
        assert detail["rejected"]

    def test_valid_empty_arrays_are_not_penalized(self):
        empty = json.dumps(
            {
                key: []
                for key in ("decisions", "action_items", "key_claims", "blockers", "next_steps")
            }
        )
        score, detail = objective_struct_score(empty)
        assert score == 100.0
        assert detail["total_items"] == 0
        assert detail["rejected"] == []

    def test_non_string_item_is_rejected_without_a_quality_claim(self):
        payload = json.loads(_FULL)
        payload["action_items"] = [{"owner": "invented"}]
        score, detail = objective_struct_score(json.dumps(payload))
        assert score == 80.0
        assert any("action_items" in item for item in detail["rejected"])

    def test_empty_object_has_no_valid_sections(self):
        score, detail = objective_struct_score("{}")
        assert score == 0.0
        assert detail["rejected"]

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


class TestResolveComparePlan:
    def test_smart_is_cloud_vs_best_local(self):
        avail = _avail(cloud=["openai", "xai"], models=["a:7b"], auto="a:7b")
        specs, judge = resolve_compare_plan("smart", "auto", avail)
        assert specs == ["openai", "ollama:a:7b"]
        assert judge == "openai"  # auto judge = preferred cloud

    def test_blank_defaults_to_smart(self):
        avail = _avail(cloud=["openai"], models=["a:7b"], auto="a:7b")
        specs, _ = resolve_compare_plan("", None, avail)
        assert specs == ["openai", "ollama:a:7b"]

    def test_local_preset_lists_all_and_stays_offline(self):
        avail = _avail(cloud=["openai"], models=["a:7b", "b:14b"], auto="b:14b")
        specs, judge = resolve_compare_plan("local", "auto", avail)
        assert specs == ["ollama:a:7b", "ollama:b:14b"]
        assert judge is None  # fully local -> no cloud judge by default

    def test_all_preset(self):
        avail = _avail(cloud=["openai", "gemini"], models=["a:7b"], auto="a:7b")
        specs, judge = resolve_compare_plan("all", "auto", avail)
        assert specs == ["openai", "gemini", "ollama:a:7b"]
        assert judge == "openai"

    def test_explicit_list_preserved(self):
        avail = _avail(cloud=["openai"])
        specs, _ = resolve_compare_plan("openai,ollama:gemma4:26b", "auto", avail)
        assert specs == ["openai", "ollama:gemma4:26b"]

    def test_explicit_judge_wins(self):
        avail = _avail(cloud=["openai"], auto="a:7b", models=["a:7b"])
        _, judge = resolve_compare_plan("smart", "gemini", avail)
        assert judge == "gemini"

    def test_judge_none_disables(self):
        avail = _avail(cloud=["openai"], auto="a:7b", models=["a:7b"])
        _, judge = resolve_compare_plan("smart", "none", avail)
        assert judge is None

    def test_no_cloud_no_judge(self):
        avail = _avail(cloud=[], models=["a:7b"], auto="a:7b")
        specs, judge = resolve_compare_plan("smart", "auto", avail)
        assert specs == ["ollama:a:7b"]
        assert judge is None


class TestSummarizeVerdict:
    def test_no_locals_returns_none(self):
        assert summarize_verdict([_result("openai", "gpt-5.5", 100.0, judge=9.0)]) is None

    def test_local_only_does_not_treat_shape_as_quality(self):
        verdict = summarize_verdict([_result("ollama", "qwen2.5:14b", 94.0)])
        assert verdict is not None
        assert "not assessed" in verdict
        assert "94" not in verdict

    def test_missing_judge_is_not_compared(self):
        results = [
            _result("openai", "gpt-5.5", 100.0, judge=9.0, cost=0.012),
            _result("ollama", "qwen2.5:14b", 100.0),
        ]
        verdict = summarize_verdict(results)
        assert verdict is not None
        assert "not compared" in verdict

    def test_scorecard_names_the_probe_and_separates_shape(self):
        card = format_scorecard([_result("ollama", "qwen2.5:14b", 100.0)])
        assert "single-call extraction probe" in card
        assert "not factual quality" in card
        assert "shape" in card

    def test_local_worth_it_when_close(self):
        results = [
            _result("openai", "gpt-5.5", 100.0, judge=9.0, cost=0.012),
            _result("ollama", "qwen2.5:14b", 94.0, judge=8.2),
        ]
        verdict = summarize_verdict(results)
        assert "worth it" in verdict
        assert "qwen2.5:14b" in verdict

    def test_cloud_leads_when_gap_large(self):
        results = [
            _result("openai", "gpt-5.5", 100.0, judge=9.5, cost=0.012),
            _result("ollama", "tiny:1b", 60.0, judge=4.0),
        ]
        verdict = summarize_verdict(results)
        assert "still leads" in verdict


class TestDetectAvailability:
    def test_detects_cloud_keys_and_ollama(self, monkeypatch):
        for var in ("OPENAI_API_KEY", "XAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-x")

        from scribe.utils import ollama_models

        monkeypatch.setattr(
            ollama_models,
            "list_installed_models",
            lambda _base_url=None: [ollama_models.OllamaModel("a:7b", 5.0)],
        )
        monkeypatch.setattr(ollama_models, "available_model_memory_gb", lambda: 24.0)

        avail = notes_eval.detect_availability()
        assert avail.cloud == ["openai"]
        assert avail.ollama_models == ["a:7b"]
        assert avail.ollama_auto == "a:7b"


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
