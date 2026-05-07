"""
中文术语搜索功能测试脚本
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.services.chinese_term_indexer import ChineseTermIndexer
from backend.services.chinese_term_client import ChineseTermClient
from backend.services.fuzzy_matcher import FuzzyMatcher
from backend.utils.logger import logger


def test_indexer_loading():
    """测试索引加载"""
    print("\n" + "="*60)
    print("测试1: 索引加载")
    print("="*60)
    
    indexer = ChineseTermIndexer()
    
    print("\n加载IMCS症状库...")
    symptom_count = indexer.load_symptom_norm("data/text/symptom_norm.csv")
    print(f"加载了 {symptom_count} 个症状术语")
    
    print("\n加载ICD-11术语库...")
    icd11_count = indexer.load_icd11_terms("data/text/SimpleTabulation-ICD-11-MMS-zh.txt")
    print(f"加载了 {icd11_count} 个ICD-11术语")
    
    print("\n加载口语化术语同义词映射...")
    colloquial_count = indexer.load_colloquial_synonyms("data/text/colloquial_synonyms.json")
    print(f"加载了 {colloquial_count} 个同义词映射")
    
    print("\n构建索引...")
    total_count = indexer.build_index()
    print(f"总共索引了 {total_count} 个术语")
    
    stats = indexer.get_stats()
    print(f"\n索引统计:")
    print(f"  - 总术语数: {stats['total_terms']}")
    print(f"  - 症状术语: {stats['symptom_terms']}")
    print(f"  - 诊断术语: {stats['diagnosis_terms']}")
    print(f"  - 索引字符: {stats['indexed_characters']}")
    print(f"  - 同义词映射: {stats['colloquial_synonyms']}")
    
    return indexer


def test_exact_match(client: ChineseTermClient):
    """测试精确匹配"""
    print("\n" + "="*60)
    print("测试2: 精确匹配")
    print("="*60)
    
    test_terms = [
        "咳嗽",
        "发热",
        "感冒",
        "腹泻",
        "肺炎",
        "支气管炎"
    ]
    
    print("\n测试术语:")
    for term in test_terms:
        result = client.search_term(term, use_fuzzy=False)
        if result:
            print(f"  ✓ '{term}' -> '{result.matched_term}' (置信度: {result.confidence:.2f}, 类型: {result.match_type})")
        else:
            print(f"  ✗ '{term}' 未找到匹配")


def test_fuzzy_match(client: ChineseTermClient):
    """测试模糊匹配"""
    print("\n" + "="*60)
    print("测试3: 模糊匹配")
    print("="*60)
    
    test_terms = [
        "咳嗽不止",
        "发高烧",
        "拉肚子",
        "肚子疼",
        "头疼",
        "流鼻涕"
    ]
    
    print("\n测试术语:")
    for term in test_terms:
        result = client.search_term(term, use_fuzzy=True)
        if result:
            print(f"  ✓ '{term}' -> '{result.matched_term}' (置信度: {result.confidence:.2f}, 类型: {result.match_type})")
        else:
            print(f"  ✗ '{term}' 未找到匹配")


def test_term_type_filter(client: ChineseTermClient):
    """测试术语类型过滤"""
    print("\n" + "="*60)
    print("测试4: 术语类型过滤")
    print("="*60)
    
    test_cases = [
        ("咳嗽", "symptom"),
        ("肺炎", "diagnosis"),
        ("发热", "symptom"),
        ("支气管炎", "diagnosis")
    ]
    
    print("\n测试术语类型过滤:")
    for term, term_type in test_cases:
        result = client.search_term(term, term_type=term_type, use_fuzzy=True)
        if result:
            print(f"  ✓ '{term}' (类型: {term_type}) -> '{result.matched_term}' (置信度: {result.confidence:.2f})")
        else:
            print(f"  ✗ '{term}' (类型: {term_type}) 未找到匹配")


def test_batch_search(client: ChineseTermClient):
    """测试批量搜索"""
    print("\n" + "="*60)
    print("测试5: 批量搜索")
    print("="*60)
    
    test_terms = [
        "咳嗽",
        "发热",
        "感冒",
        "腹泻",
        "肺炎",
        "支气管炎",
        "鼻塞",
        "流鼻涕"
    ]
    
    print(f"\n批量搜索 {len(test_terms)} 个术语...")
    start_time = time.time()
    results = client.batch_search(test_terms)
    elapsed_time = time.time() - start_time
    
    matched_count = sum(1 for r in results.values() if r is not None)
    print(f"\n匹配结果: {matched_count}/{len(test_terms)}")
    print(f"耗时: {elapsed_time*1000:.2f}ms")
    
    print("\n详细结果:")
    for term, result in results.items():
        if result:
            print(f"  ✓ '{term}' -> '{result.matched_term}' (置信度: {result.confidence:.2f})")
        else:
            print(f"  ✗ '{term}' 未找到匹配")


def test_performance(client: ChineseTermClient):
    """测试性能"""
    print("\n" + "="*60)
    print("测试6: 性能测试")
    print("="*60)
    
    test_terms = ["咳嗽", "发热", "感冒", "腹泻", "肺炎"] * 20
    
    print(f"\n测试 {len(test_terms)} 次搜索...")
    start_time = time.time()
    
    for term in test_terms:
        client.search_term(term, use_fuzzy=True)
    
    elapsed_time = time.time() - start_time
    avg_time = (elapsed_time / len(test_terms)) * 1000
    
    print(f"总耗时: {elapsed_time:.2f}s")
    print(f"平均每次搜索: {avg_time:.2f}ms")


def test_fuzzy_matcher():
    """测试模糊匹配器"""
    print("\n" + "="*60)
    print("测试7: 模糊匹配器算法")
    print("="*60)
    
    matcher = FuzzyMatcher(threshold=0.7)
    
    test_cases = [
        ("咳嗽", "咳嗽不止"),
        ("发热", "发高烧"),
        ("感冒", "感冒了"),
        ("腹泻", "拉肚子")
    ]
    
    print("\n相似度计算测试:")
    for term1, term2 in test_cases:
        similarity = matcher.calculate_similarity(term1, term2)
        jaccard = matcher.calculate_jaccard_similarity(term1, term2)
        levenshtein = matcher.calculate_levenshtein_similarity(term1, term2)
        print(f"  '{term1}' vs '{term2}':")
        print(f"    - SequenceMatcher: {similarity:.3f}")
        print(f"    - Jaccard: {jaccard:.3f}")
        print(f"    - Levenshtein: {levenshtein:.3f}")


def main():
    """主测试函数"""
    print("\n" + "="*60)
    print("中文术语搜索功能测试")
    print("="*60)
    
    try:
        indexer = test_indexer_loading()
        
        client = ChineseTermClient(
            indexer=indexer,
            fuzzy_threshold=0.7,
            exact_match_bonus=0.2
        )
        
        test_exact_match(client)
        test_fuzzy_match(client)
        test_term_type_filter(client)
        test_batch_search(client)
        test_performance(client)
        test_fuzzy_matcher()
        
        print("\n" + "="*60)
        print("所有测试完成！")
        print("="*60)
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
