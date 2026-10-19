"""UT — model_config.stage_model: per-stage model resolution.

Resolution contract: ``"default"`` / empty / absent → ``None`` (use the SDK
default, i.e. .claude/settings.json); a concrete model id → returned verbatim.
``None`` is what makes the spawn pass ``model=None`` to the backend so the SDK
applies its configured default (the fix for the codegen 503 — pointing codegen
at a model the gateway lacked).
"""

from ascendc_devkit.orchestration import model_config


def test_default_token_constant():
    assert model_config.DEFAULT_TOKEN == "default"


def test_absent_stage_returns_none(monkeypatch):
    monkeypatch.setattr(model_config, "STAGE_MODEL_MAP", {})
    assert model_config.stage_model("codegen") is None


def test_default_token_returns_none(monkeypatch):
    monkeypatch.setattr(model_config, "STAGE_MODEL_MAP", {"codegen": "default"})
    assert model_config.stage_model("codegen") is None


def test_empty_string_returns_none(monkeypatch):
    monkeypatch.setattr(model_config, "STAGE_MODEL_MAP", {"codegen": ""})
    assert model_config.stage_model("codegen") is None


def test_concrete_id_returned_verbatim(monkeypatch):
    monkeypatch.setattr(model_config, "STAGE_MODEL_MAP",
                        {"codegen": "deepseek-v4-pro"})
    assert model_config.stage_model("codegen") == "deepseek-v4-pro"


def test_other_stages_independent(monkeypatch):
    # A concrete id on one stage must not leak into another.
    monkeypatch.setattr(model_config, "STAGE_MODEL_MAP",
                        {"codegen": "deepseek-v4-pro"})
    assert model_config.stage_model("validate") is None


def test_shipped_codegen_uses_sdk_default():
    # Regression guard for the 503 crash: the shipped config points codegen at
    # "default" (SDK default) so it can never 503 on a missing channel. If you
    # intentionally switch codegen to a concrete model, update this assertion
    # to that id (and confirm the gateway has the channel first).
    assert model_config.stage_model("codegen") is None


def test_no_dead_default_module_attr():
    # models.default was a dead config — DEFAULT_MODEL had zero consumers and
    # was removed (§1.4). Ensure nobody reintroduces the dangling attribute.
    assert not hasattr(model_config, "DEFAULT_MODEL")
