"""Tests for backend.llm.router — Model routing.

Covers:
- ModelConfig dataclass and to_dict()
- DEFAULT_MODEL values
- get_model() returns the default
- get_all_models() returns list of dicts
- __all__ exports
"""

from backend.llm.router import (
    DEFAULT_MODEL,
    ModelConfig,
    get_all_models,
    get_model,
)


class TestModelConfig:

    def test_dataclass_fields(self):
        mc = ModelConfig(
            id="test-id",
            name="Test Model",
            provider="test-provider",
            model="test-model-v1",
        )
        assert mc.id == "test-id"
        assert mc.name == "Test Model"
        assert mc.provider == "test-provider"
        assert mc.model == "test-model-v1"
        assert mc.icon == ""
        assert mc.description == ""

    def test_dataclass_custom_icon_and_description(self):
        mc = ModelConfig(
            id="x",
            name="X",
            provider="p",
            model="m",
            icon="star",
            description="fast model",
        )
        assert mc.icon == "star"
        assert mc.description == "fast model"

    def test_to_dict_returns_expected_keys(self):
        mc = ModelConfig(
            id="test",
            name="Test",
            provider="prov",
            model="mod",
            icon="ic",
            description="desc",
        )
        d = mc.to_dict()
        assert d == {
            "id": "test",
            "name": "Test",
            "icon": "ic",
            "description": "desc",
        }

    def test_to_dict_excludes_provider_and_model(self):
        mc = ModelConfig(id="a", name="b", provider="c", model="d")
        d = mc.to_dict()
        assert "provider" not in d
        assert "model" not in d


class TestDefaultModel:

    def test_default_model_is_anthropic(self):
        assert DEFAULT_MODEL.provider == "anthropic"

    def test_default_model_id(self):
        assert DEFAULT_MODEL.id == "anthropic"

    def test_default_model_name(self):
        assert DEFAULT_MODEL.name == "Claude Sonnet 4.5"

    def test_default_model_model_matches_config(self):
        from backend.config import ANTHROPIC_CHAT_MODEL
        assert DEFAULT_MODEL.model == ANTHROPIC_CHAT_MODEL


class TestGetModel:

    def test_returns_default_model(self):
        result = get_model()
        assert result is DEFAULT_MODEL

    def test_returns_model_config_instance(self):
        result = get_model()
        assert isinstance(result, ModelConfig)


class TestGetAllModels:

    def test_returns_list(self):
        result = get_all_models()
        assert isinstance(result, list)

    def test_contains_one_model(self):
        result = get_all_models()
        assert len(result) == 1

    def test_first_entry_matches_default_model_dict(self):
        result = get_all_models()
        assert result[0] == DEFAULT_MODEL.to_dict()


class TestModuleExports:

    def test_all_exports(self):
        from backend.llm import router
        assert "ModelConfig" in router.__all__
        assert "DEFAULT_MODEL" in router.__all__
        assert "get_model" in router.__all__
        assert "get_all_models" in router.__all__
