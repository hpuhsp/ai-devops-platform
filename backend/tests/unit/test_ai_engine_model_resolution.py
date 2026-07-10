from app.services.ai.engine import AIEngine


def test_openai_compatible_endpoint_prefixes_local_model_path():
    resolved = AIEngine._resolve_litellm_model(
        "/data/Qwen3.6/Qwen/Qwen3.6-35B-A3B-FP8",
        "http://localhost:8000/v1",
        "custom",
    )

    assert resolved == "openai//data/Qwen3.6/Qwen/Qwen3.6-35B-A3B-FP8"


def test_provider_prefixed_model_without_api_base_is_left_as_is():
    resolved = AIEngine._resolve_litellm_model(
        "deepseek/deepseek-chat",
        None,
        "deepseek",
    )

    assert resolved == "deepseek/deepseek-chat"


def test_known_provider_without_api_base_gets_provider_prefix():
    resolved = AIEngine._resolve_litellm_model(
        "deepseek-chat",
        None,
        "deepseek",
    )

    assert resolved == "deepseek/deepseek-chat"
