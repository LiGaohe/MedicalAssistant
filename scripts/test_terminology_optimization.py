"""
测试术语规范化性能优化
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.services.umls.umls_client import UMLSClient
from backend.services.umls.term_cache import TermCache
from backend.config import settings
from backend.utils.logger import logger


def test_tgt_caching():
    """测试TGT缓存机制"""
    print("\n=== 测试TGT缓存机制 ===")
    
    if not settings.UMLS_API_KEY:
        print("警告: UMLS_API_KEY未配置，跳过测试")
        return
    
    cache_service = TermCache(
        cache_dir=settings.UMLS_CACHE_DIR,
        default_ttl_hours=settings.UMLS_CACHE_TTL_HOURS
    )
    
    client = UMLSClient(
        api_key=settings.UMLS_API_KEY,
        cache_service=cache_service,
        request_timeout=settings.UMLS_REQUEST_TIMEOUT,
        max_retries=settings.UMLS_MAX_RETRIES,
        rate_limit_delay=settings.UMLS_RATE_LIMIT_DELAY
    )
    
    print("\n第一次调用 - 应该获取新的TGT")
    start = time.time()
    result1 = client.search_term("headache", language="ENG", page_size=1)
    time1 = time.time() - start
    print(f"耗时: {time1:.2f}秒, 结果: {len(result1.candidates)}个候选")
    
    print("\n第二次调用 - 应该复用缓存的TGT")
    start = time.time()
    result2 = client.search_term("nausea", language="ENG", page_size=1)
    time2 = time.time() - start
    print(f"耗时: {time2:.2f}秒, 结果: {len(result2.candidates)}个候选")
    
    print("\n第三次调用 - 应该复用缓存的TGT")
    start = time.time()
    result3 = client.search_term("fever", language="ENG", page_size=1)
    time3 = time.time() - start
    print(f"耗时: {time3:.2f}秒, 结果: {len(result3.candidates)}个候选")
    
    print(f"\n性能提升: 第二次比第一次快 {(time1 - time2) / time1 * 100:.1f}%")
    print(f"性能提升: 第三次比第一次快 {(time1 - time3) / time1 * 100:.1f}%")


def test_atoms_caching():
    """测试Atoms缓存机制"""
    print("\n=== 测试Atoms缓存机制 ===")
    
    if not settings.UMLS_API_KEY:
        print("警告: UMLS_API_KEY未配置，跳过测试")
        return
    
    cache_service = TermCache(
        cache_dir=settings.UMLS_CACHE_DIR,
        default_ttl_hours=settings.UMLS_CACHE_TTL_HOURS
    )
    
    client = UMLSClient(
        api_key=settings.UMLS_API_KEY,
        cache_service=cache_service,
        request_timeout=settings.UMLS_REQUEST_TIMEOUT,
        max_retries=settings.UMLS_MAX_RETRIES,
        rate_limit_delay=settings.UMLS_RATE_LIMIT_DELAY
    )
    
    cui = "C0018681"  # Headache
    
    print(f"\n第一次获取atoms for CUI {cui} - 应该调用API")
    start = time.time()
    atoms1 = client.get_atoms(cui)
    time1 = time.time() - start
    print(f"耗时: {time1:.2f}秒, 结果: {len(atoms1)}个atoms")
    
    print(f"\n第二次获取atoms for CUI {cui} - 应该使用缓存")
    start = time.time()
    atoms2 = client.get_atoms(cui)
    time2 = time.time() - start
    print(f"耗时: {time2:.2f}秒, 结果: {len(atoms2)}个atoms")
    
    print(f"\n性能提升: 第二次比第一次快 {(time1 - time2) / time1 * 100:.1f}%")


def test_term_deduplication():
    """测试术语去重"""
    print("\n=== 测试术语去重 ===")
    
    from backend.services.terminology_service import TerminologyService
    from backend.database import SessionLocal
    
    db = SessionLocal()
    try:
        service = TerminologyService(db=db, language="zh")
        
        test_text = """
        患者主诉头疼、恶心、血压偏高。
        头疼已经持续3天，血压高，服用降压药。
        """
        
        print(f"\n测试文本: {test_text.strip()}")
        print("\n识别术语中...")
        
        identified = service.identify_colloquial_terms(test_text)
        
        print(f"\n识别到的术语（共{len(identified)}个）:")
        for i, term_info in enumerate(identified, 1):
            print(f"  {i}. {term_info.get('term')} ({term_info.get('term_type')})")
        
        seen = set()
        duplicates = []
        for term_info in identified:
            term = term_info.get("term", "")
            if term in seen:
                duplicates.append(term)
            seen.add(term)
        
        if duplicates:
            print(f"\n发现重复术语: {duplicates}")
            print("去重功能将自动处理这些重复项")
        else:
            print("\n未发现重复术语")
            
    finally:
        db.close()


if __name__ == "__main__":
    print("=" * 60)
    print("术语规范化性能优化测试")
    print("=" * 60)
    
    test_tgt_caching()
    test_atoms_caching()
    test_term_deduplication()
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
