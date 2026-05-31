import sys
import os

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
backend_dir = os.path.join(parent_dir, 'backend')
sys.path.insert(0, backend_dir)

print("=== 测试LLM日志记录功能 ===\n")
print(f"Backend目录: {backend_dir}")
print(f"Python路径包含: {sys.path[:3]}")

try:
    from database import SessionLocal
    from services.llm.llm_service import LLMService
    
    print("\n导入成功!")
    
    db = SessionLocal()
    try:
        llm_service = LLMService(db)
        print(f"LLM服务初始化成功")
        print(f"可用adapter数量: {len(llm_service.adapters)}")
        print(f"原始响应日志记录器: {llm_service._llm_raw_logger}")
        
        if llm_service.adapters:
            test_prompt = "请生成一段简短的医学术语：发热"
            print(f"\n发送测试提示词: {test_prompt}")
            
            response = llm_service.generate(test_prompt)
            print(f"\n响应成功:")
            print(f"- 响应长度: {len(response.text)} 字符")
            print(f"- 模型: {response.model}")
            print(f"- 提供商: {response.provider}")
            print(f"\n响应内容预览 (前200字):\n{response.text[:200]}")
            
            print("\n=== 测试完成 ===")
            print(f"日志文件应保存在: data/logs/llm_raw/ 目录")
            print("请检查该目录下的日志文件，确认原始响应是否被正确记录")
        else:
            print("\n警告: 没有可用的LLM adapter")
            print("请先配置LLM模型")
            
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

except ImportError as e:
    print(f"导入失败: {e}")
    print("尝试其他导入方式...")
    
    import importlib.util
    spec = importlib.util.spec_from_file_location("database", os.path.join(backend_dir, "database.py"))
    database_module = importlib.util.module_from_spec(spec)
    sys.modules['database'] = database_module
    spec.loader.exec_module(database_module)
    
    db = database_module.SessionLocal()
    print("Database导入成功")
