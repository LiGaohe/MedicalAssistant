import pytest
from unittest.mock import Mock, patch, MagicMock
from backend.services.llm.base import LLMRequest, LLMResponse
from backend.services.llm.openai_compatible_adapter import OpenAICompatibleAdapter
from backend.services.llm.prompts import PromptManager
from backend.services.llm.llm_service import LLMService


def test_llm_request_dataclass():
    request = LLMRequest(
        prompt="测试提示词",
        max_tokens=100,
        temperature=0.5
    )
    assert request.prompt == "测试提示词"
    assert request.max_tokens == 100
    assert request.temperature == 0.5


def test_llm_response_dataclass():
    response = LLMResponse(
        text="测试响应",
        model="qwen-7b",
        provider="modelscope",
        usage={"total_tokens": 50},
        finish_reason="stop"
    )
    assert response.text == "测试响应"
    assert response.model == "qwen-7b"
    assert response.provider == "modelscope"


def test_prompt_manager_render():
    manager = PromptManager()
    prompt = manager.render(
        "term_normalization",
        term="头疼",
        context="患者主诉头疼三天"
    )
    assert "头疼" in prompt
    assert "患者主诉头疼三天" in prompt


def test_prompt_manager_missing_var():
    manager = PromptManager()
    with pytest.raises(ValueError, match="Missing required variables"):
        manager.render("term_normalization", term="头疼")


@patch('httpx.Client')
def test_openai_compatible_adapter_generate(mock_client):
    mock_response = Mock()
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {"content": "测试响应"},
                "finish_reason": "stop"
            }
        ],
        "usage": {"total_tokens": 50}
    }
    mock_response.raise_for_status = Mock()
    
    mock_client_instance = MagicMock()
    mock_client_instance.post.return_value = mock_response
    mock_client.return_value.__enter__.return_value = mock_client_instance
    
    adapter = OpenAICompatibleAdapter({
        "model_name": "qwen-7b",
        "api_endpoint": "https://test.com/v1/chat/completions",
        "provider_name": "test"
    })
    
    request = LLMRequest(prompt="测试")
    response = adapter.generate(request)
    
    assert response.text == "测试响应"
    assert response.model == "qwen-7b"
    assert response.provider == "test"


@patch('httpx.Client')
def test_openai_compatible_adapter_with_api_key(mock_client):
    mock_response = Mock()
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {"content": "测试响应"},
                "finish_reason": "stop"
            }
        ],
        "usage": {"total_tokens": 50}
    }
    mock_response.raise_for_status = Mock()
    
    mock_client_instance = MagicMock()
    mock_client_instance.post.return_value = mock_response
    mock_client.return_value.__enter__.return_value = mock_client_instance
    
    adapter = OpenAICompatibleAdapter({
        "model_name": "gpt-3.5-turbo",
        "api_key": "test-key",
        "provider_name": "openai"
    })
    
    request = LLMRequest(prompt="测试")
    response = adapter.generate(request)
    
    assert response.text == "测试响应"
    assert response.model == "gpt-3.5-turbo"
    assert response.provider == "openai"


def test_llm_service_generate_json():
    mock_db = Mock()
    mock_config = Mock()
    mock_config.config_name = "test-config"
    mock_config.model_name = "qwen-7b"
    mock_config.max_tokens = 2048
    mock_config.temperature = "0.7"
    
    mock_db.query.return_value.filter.return_value.all.return_value = []
    mock_db.query.return_value.filter.return_value.first.return_value = mock_config
    
    service = LLMService(mock_db)
    
    mock_adapter = Mock()
    mock_adapter.generate.return_value = LLMResponse(
        text='{"result": "测试"}',
        model="qwen-7b",
        provider="modelscope",
        usage={},
        finish_reason="stop"
    )
    mock_adapter.validate_response.return_value = True
    service.adapters["test-config"] = mock_adapter
    
    result = service.generate_json("测试提示", "test-config")
    
    assert result == {"result": "测试"}


def test_llm_service_no_adapters():
    mock_db = Mock()
    mock_db.query.return_value.filter.return_value.all.return_value = []
    
    service = LLMService(mock_db)
    
    with pytest.raises(RuntimeError, match="No active LLM adapters"):
        service.generate("测试提示")
