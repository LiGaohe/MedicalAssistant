import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.translation_service import TranslationService
from backend.utils.logger import logger


def test_translation_service():
    print("=" * 80)
    print("测试翻译服务")
    print("=" * 80)

    print("\n1. 初始化翻译服务...")
    service = TranslationService(model_name="Helsinki-NLP/opus-mt-zh-en", device="cpu")

    if not service.is_available():
        print("❌ 翻译服务初始化失败")
        return

    print("✅ 翻译服务初始化成功")

    test_terms = [
        "头痛",
        "高血压",
        "糖尿病",
        "心肌梗死",
        "上呼吸道感染",
        "支气管炎",
        "胃溃疡",
        "肾功能不全",
        "甲状腺功能亢进",
        "类风湿性关节炎"
    ]

    print(f"\n2. 测试翻译功能（共{len(test_terms)}个术语）...")
    print("-" * 80)

    total_time = 0
    success_count = 0

    for i, term in enumerate(test_terms, 1):
        print(f"\n[{i}/{len(test_terms)}] 测试术语: {term}")

        start_time = time.time()
        translated = service.translate_zh_to_en(term)
        elapsed_time = time.time() - start_time
        total_time += elapsed_time

        if translated:
            print(f"  ✅ 翻译结果: {translated}")
            print(f"  ⏱️  耗时: {elapsed_time:.3f}秒")
            success_count += 1
        else:
            print(f"  ❌ 翻译失败")

    print("\n" + "=" * 80)
    print("测试结果汇总")
    print("=" * 80)
    print(f"总测试术语数: {len(test_terms)}")
    print(f"成功翻译数: {success_count}")
    print(f"成功率: {success_count / len(test_terms) * 100:.1f}%")
    print(f"总耗时: {total_time:.3f}秒")
    print(f"平均耗时: {total_time / len(test_terms):.3f}秒/术语")
    print("=" * 80)


def compare_with_llm():
    print("\n" + "=" * 80)
    print("对比测试：翻译服务 vs LLM推理模型")
    print("=" * 80)

    print("\n注意：此测试需要LLM服务可用")
    print("如果LLM服务不可用，将跳过对比测试")

    try:
        from backend.database import get_db
        from backend.services.llm.llm_service import LLMService
        from backend.services.terminology_service import TerminologyService

        db = next(get_db())
        llm_service = LLMService(db)

        if not llm_service.adapters:
            print("❌ LLM服务不可用，跳过对比测试")
            return

        term_service_with_translation = TerminologyService(
            db=db,
            llm_service=llm_service,
            language="zh"
        )

        term_service_without_translation = TerminologyService(
            db=db,
            llm_service=llm_service,
            translation_service=None,
            language="zh"
        )

        test_term = "高血压"

        print(f"\n测试术语: {test_term}")

        print("\n1. 使用翻译服务...")
        start_time = time.time()
        result1 = term_service_with_translation._translate_term_to_english(test_term, "")
        time1 = time.time() - start_time
        print(f"   结果: {result1}")
        print(f"   耗时: {time1:.3f}秒")

        print("\n2. 使用LLM推理模型...")
        start_time = time.time()
        result2 = term_service_without_translation._translate_term_to_english(test_term, "")
        time2 = time.time() - start_time
        print(f"   结果: {result2}")
        print(f"   耗时: {time2:.3f}秒")

        print("\n" + "=" * 80)
        print("对比结果")
        print("=" * 80)
        print(f"翻译服务结果: {result1}")
        print(f"LLM推理结果: {result2}")
        print(f"翻译服务耗时: {time1:.3f}秒")
        print(f"LLM推理耗时: {time2:.3f}秒")
        print(f"速度提升: {time2 / time1:.1f}倍")
        print("=" * 80)

    except Exception as e:
        print(f"❌ 对比测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_translation_service()

    print("\n是否进行对比测试？(y/n): ", end="")
    choice = input().strip().lower()
    if choice == 'y':
        compare_with_llm()
