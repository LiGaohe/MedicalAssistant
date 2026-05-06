"""
测试术语规范化并行优化

对比串行和并行模式的性能差异
"""
import sys
import os
import time
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal
from backend.services.terminology_service import TerminologyService
from backend.services.llm.llm_service import LLMService
from backend.services.translation_service import TranslationService
from backend.config import settings


def test_parallel_vs_serial():
    """测试并行和串行模式的性能对比"""
    
    test_text = """
    患者主诉头疼三天，伴有恶心、呕吐。既往有高血压病史，长期服用降压药。
    最近感觉心慌、胸闷，睡眠不好。检查发现血压偏高，心率偏快。
    医生建议做心电图检查，排除心脏问题。
    """
    
    print("=" * 60)
    print("术语规范化并行优化测试")
    print("=" * 60)
    print(f"测试文本长度: {len(test_text)} 字符")
    print()
    
    db = SessionLocal()
    
    try:
        llm_service = LLMService(db)
        translation_service = TranslationService(
            model_name=settings.TRANSLATION_MODEL,
            device=settings.TRANSLATION_DEVICE
        )
        
        term_service = TerminologyService(
            db=db,
            llm_service=llm_service,
            translation_service=translation_service,
            language="zh"
        )
        
        print("测试串行模式...")
        start_time = time.time()
        serial_results = term_service.extract_and_normalize_terms(
            test_text, 
            use_parallel=False
        )
        serial_time = time.time() - start_time
        print(f"串行模式完成，耗时: {serial_time:.2f}秒")
        print(f"识别到 {len(serial_results)} 个术语")
        print()
        
        print("测试并行模式...")
        start_time = time.time()
        parallel_results = term_service.extract_and_normalize_terms(
            test_text,
            use_parallel=True
        )
        parallel_time = time.time() - start_time
        print(f"并行模式完成，耗时: {parallel_time:.2f}秒")
        print(f"识别到 {len(parallel_results)} 个术语")
        print()
        
        print("=" * 60)
        print("性能对比结果")
        print("=" * 60)
        print(f"串行模式耗时: {serial_time:.2f}秒")
        print(f"并行模式耗时: {parallel_time:.2f}秒")
        
        if parallel_time > 0:
            speedup = serial_time / parallel_time
            print(f"性能提升: {speedup:.2f}x")
        
        print()
        print("术语识别结果:")
        for term in parallel_results:
            print(f"  - {term.original_term} -> {term.normalized_term} (source: {term.source}, confidence: {term.confidence:.2f})")
        
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


def test_batch_translation():
    """测试批量翻译功能"""
    print("=" * 60)
    print("批量翻译测试")
    print("=" * 60)
    
    test_terms = ["头疼", "高血压", "恶心", "心慌", "胸闷"]
    
    try:
        translation_service = TranslationService(
            model_name=settings.TRANSLATION_MODEL,
            device=settings.TRANSLATION_DEVICE
        )
        
        if not translation_service.is_available():
            print("翻译服务不可用")
            return
        
        print(f"测试术语: {test_terms}")
        print()
        
        print("单个翻译测试:")
        start_time = time.time()
        single_results = {}
        for term in test_terms:
            result = translation_service.translate_zh_to_en(term)
            single_results[term] = result
            print(f"  {term} -> {result}")
        single_time = time.time() - start_time
        print(f"单个翻译耗时: {single_time:.2f}秒")
        print()
        
        print("批量翻译测试:")
        start_time = time.time()
        batch_results = translation_service.batch_translate_zh_to_en(test_terms)
        batch_time = time.time() - start_time
        for term, trans in batch_results.items():
            print(f"  {term} -> {trans}")
        print(f"批量翻译耗时: {batch_time:.2f}秒")
        print()
        
        print(f"性能提升: {single_time / batch_time:.2f}x")
        
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()


async def test_async_umls():
    """测试异步UMLS客户端"""
    print("=" * 60)
    print("异步UMLS客户端测试")
    print("=" * 60)
    
    if not settings.UMLS_ENABLED or not settings.UMLS_API_KEY:
        print("UMLS未启用或未配置API Key")
        return
    
    from backend.services.umls.async_umls_client import AsyncUMLSClient
    from backend.services.umls.term_cache import TermCache
    
    try:
        cache_service = TermCache(
            cache_dir=settings.UMLS_CACHE_DIR,
            default_ttl_hours=settings.UMLS_CACHE_TTL_HOURS
        )
        
        async_client = AsyncUMLSClient(
            api_key=settings.UMLS_API_KEY,
            cache_service=cache_service,
            max_concurrent=5
        )
        
        test_terms = ["headache", "hypertension", "nausea", "palpitation", "chest pain"]
        
        print(f"测试术语: {test_terms}")
        print()
        
        print("并行搜索测试:")
        start_time = time.time()
        results = await async_client.batch_search(test_terms, language="ENG")
        parallel_time = time.time() - start_time
        
        for term, result in results.items():
            if result.error:
                print(f"  {term}: 错误 - {result.error}")
            else:
                print(f"  {term}: 找到 {len(result.candidates)} 个候选")
        
        print(f"并行搜索耗时: {parallel_time:.2f}秒")
        
        await async_client.close()
        
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("术语规范化并行优化测试套件")
    print("=" * 60 + "\n")
    
    print("1. 批量翻译测试")
    test_batch_translation()
    print()
    
    print("2. 异步UMLS客户端测试")
    asyncio.run(test_async_umls())
    print()
    
    print("3. 并行 vs 串行模式对比测试")
    test_parallel_vs_serial()
