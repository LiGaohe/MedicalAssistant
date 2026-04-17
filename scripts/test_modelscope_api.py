"""
测试魔搭API集成
"""
import sys
sys.path.insert(0, 'd:/practice/MedicalAssisstant')

from backend.database import SessionLocal
from backend.services.llm.llm_service import LLMService
from backend.services.llm.base import LLMRequest

def test_modelscope_api():
    print("=" * 60)
    print("测试魔搭API集成")
    print("=" * 60)
    
    db = SessionLocal()
    
    try:
        service = LLMService(db)
        
        print("\n📋 可用的LLM配置:")
        models = service.get_available_models()
        for model in models:
            print(f"  - {model['name']}: {model['model']} ({model['provider']})")
        
        if not models:
            print("  ⚠️  没有可用的LLM配置")
            return
        
        print("\n🧪 测试API调用:")
        request = LLMRequest(
            prompt="你好，请用一句话介绍自己。",
            max_tokens=100,
            temperature=0.7
        )
        
        response = service.generate(request.prompt)
        
        print(f"\n✅ API调用成功!")
        print(f"模型: {response.model}")
        print(f"服务商: {response.provider}")
        print(f"响应: {response.text}")
        print(f"Token使用: {response.usage}")
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    test_modelscope_api()
