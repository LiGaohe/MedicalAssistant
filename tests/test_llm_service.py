import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from backend.services.llm.base import LLMRequest, LLMResponse, LLMStreamChunk
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


def test_llm_stream_chunk_dataclass():
    chunk = LLMStreamChunk(
        text="测试chunk",
        model="qwen-7b",
        provider="modelscope",
        finish_reason=None,
        is_final=False
    )
    assert chunk.text == "测试chunk"
    assert chunk.model == "qwen-7b"
    assert chunk.is_final == False
    
    final_chunk = LLMStreamChunk(
        text="完整响应",
        model="qwen-7b",
        provider="modelscope",
        finish_reason="stop",
        is_final=True,
        usage={"total_tokens": 100}
    )
    assert final_chunk.is_final == True
    assert final_chunk.finish_reason == "stop"


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
def test_openai_compatible_adapter_generate_stream(mock_client):
    """测试流式生成功能"""
    mock_stream_response = MagicMock()
    
    stream_lines = [
        "data: {\"choices\": [{\"delta\": {\"content\": \"测试\"}}]}",
        "data: {\"choices\": [{\"delta\": {\"content\": \"响应\"}}]}",
        "data: {\"choices\": [{\"delta\": {\"content\": \"完成\"}, \"finish_reason\": \"stop\"}], \"usage\": {\"total_tokens\": 50}}",
        "data: [DONE]"
    ]
    mock_stream_response.iter_lines.return_value = stream_lines
    mock_stream_response.raise_for_status = Mock()
    
    mock_client_instance = MagicMock()
    mock_client_instance.stream.return_value.__enter__.return_value = mock_stream_response
    mock_client.return_value.__enter__.return_value = mock_client_instance
    
    adapter = OpenAICompatibleAdapter({
        "model_name": "qwen-7b",
        "api_endpoint": "https://test.com/v1/chat/completions",
        "provider_name": "test"
    })
    
    request = LLMRequest(prompt="测试", stream=True)
    chunks = list(adapter.generate_stream(request))
    
    assert len(chunks) > 0
    assert chunks[0].text == "测试"
    assert chunks[-1].is_final == True
    assert chunks[-1].finish_reason == "stop"


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
    mock_config.json_mode = False
    mock_config.thinking_enabled = False
    mock_config.thinking_effort = "high"
    mock_config.api_endpoint = "https://test.com/v1"
    mock_config.api_key = None
    mock_config.provider = "test"
    mock_config.is_active = True
    
    mock_db.query.return_value.filter.return_value.all.return_value = [mock_config]
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
    service.adapter_configs["test-config"] = {
        "max_tokens": 2048,
        "temperature": 0.7,
        "json_mode": False,
        "thinking_enabled": False,
        "thinking_effort": "high"
    }
    
    result = service.generate_json("测试提示", "test-config")
    
    assert result == {"result": "测试"}


def test_llm_service_no_adapters():
    mock_db = Mock()
    mock_all_configs = []
    mock_db.query.return_value.filter.return_value.all.return_value = []
    mock_db.query.return_value.all.return_value = mock_all_configs
    
    service = LLMService(mock_db)
    
    with pytest.raises(RuntimeError, match="No active LLM adapters"):
        service.generate("测试提示")


def test_llm_service_generate_stream_to_response():
    """测试流式生成转换为完整响应"""
    mock_db = Mock()
    mock_db.query.return_value.filter.return_value.all.return_value = []
    
    service = LLMService(mock_db)
    
    mock_adapter = Mock()
    chunks = [
        LLMStreamChunk(text="测试", model="qwen-7b", provider="test", is_final=False),
        LLMStreamChunk(text="响应", model="qwen-7b", provider="test", is_final=False),
        LLMStreamChunk(text="测试响应完成", model="qwen-7b", provider="test", finish_reason="stop", is_final=True, usage={"total_tokens": 50})
    ]
    mock_adapter.generate_stream.return_value = chunks
    service.adapters["test-config"] = mock_adapter
    service.adapter_configs["test-config"] = {
        "max_tokens": 2048,
        "temperature": 0.7,
        "json_mode": False,
        "thinking_enabled": False,
        "thinking_effort": "high"
    }
    
    response = service.generate_stream_to_response("测试提示", "test-config")
    
    assert response.text == "测试响应完成"
    assert response.model == "qwen-7b"
    assert response.finish_reason == "stop"
