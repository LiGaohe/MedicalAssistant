import sys
sys.path.insert(0, '.')

from backend.config import settings
from backend.services.umls.umls_client import UMLSClient
from backend.services.umls.term_cache import TermCache
from backend.utils.logger import logger


def test_umls_connection():
    print("=" * 50)
    print("UMLS 连接测试")
    print("=" * 50)
    
    print(f"\n配置检查:")
    print(f"  UMLS_ENABLED: {settings.UMLS_ENABLED}")
    print(f"  UMLS_API_KEY: {settings.UMLS_API_KEY[:8]}..." if settings.UMLS_API_KEY else "  UMLS_API_KEY: 未配置")
    print(f"  UMLS_CACHE_DIR: {settings.UMLS_CACHE_DIR}")
    
    if not settings.UMLS_ENABLED:
        print("\n⚠️ UMLS未启用，请在.env中设置 UMLS_ENABLED=true")
        return False
    
    if not settings.UMLS_API_KEY:
        print("\n⚠️ UMLS_API_KEY未配置")
        return False
    
    print("\n初始化UMLS客户端...")
    cache = TermCache(
        cache_dir=settings.UMLS_CACHE_DIR,
        default_ttl_hours=settings.UMLS_CACHE_TTL_HOURS
    )
    
    client = UMLSClient(
        api_key=settings.UMLS_API_KEY,
        cache_service=cache,
        request_timeout=settings.UMLS_REQUEST_TIMEOUT,
        max_retries=settings.UMLS_MAX_RETRIES,
        rate_limit_delay=settings.UMLS_RATE_LIMIT_DELAY
    )
    
    print("\n执行健康检查...")
    if client.health_check():
        print("✅ UMLS连接成功！")
    else:
        print("❌ UMLS连接失败")
        return False
    
    print("\n测试术语查询...")
    test_terms = ["头痛", "headache", "发烧", "高血压"]
    
    for term in test_terms:
        print(f"\n查询术语: '{term}'")
        result = client.search_term(term, language="CHI" if any('\u4e00' <= c <= '\u9fff' for c in term) else "ENG")
        
        if result.error:
            print(f"  ❌ 查询错误: {result.error}")
        elif result.candidates:
            print(f"  ✅ 找到 {len(result.candidates)} 个候选:")
            for i, c in enumerate(result.candidates[:3]):
                print(f"     {i+1}. {c.term} (CUI: {c.cui}, Score: {c.score:.2f})")
        else:
            print(f"  ⚠️ 未找到匹配")
    
    print("\n缓存统计:")
    stats = cache.get_stats()
    print(f"  内存缓存: {stats['memory_cache_size']} 条")
    print(f"  文件缓存: {stats['file_cache_size']} 条")
    
    print("\n" + "=" * 50)
    print("测试完成")
    print("=" * 50)
    return True


if __name__ == "__main__":
    test_umls_connection()
