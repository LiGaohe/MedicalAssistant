"""
测试ASR文本纠错功能

验证LLM是否能正确识别和修正拼音相似的错别字
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.llm.llm_service import LLMService
from backend.services.llm.prompts import PromptManager
import json


def test_asr_correction():
    """测试ASR文本纠错功能"""
    
    print("=" * 80)
    print("测试ASR文本纠错功能")
    print("=" * 80)
    
    llm_service = LLMService()
    prompt_manager = PromptManager(language="zh")
    
    test_cases = [
        {
            "name": "日常用语纠错",
            "transcript": "[spk0]: 你好，请问哪里不舒服？\n[spk1]: 医生，我这几天一直头疼，特别是早上起来的时候。\n[spk0]: 头疼持续多长时间了？\n[spk1]: 大概三天了。\n[spk0]: 有没有恶心、呕吐的症状？\n[spk1]: 没有。\n[spk0]: 我给您量一下血压。一百四十五九十五，血压偏高。\n[spk0]: 是的，考虑是高血压引起的头疼。\n[spk0]: 我给您开点降压药，每天一次，早上吃。注意少吃闲的食物，多休息。",
            "expected_corrections": ["闲的食物" → "咸的食物"],
            "description": "测试日常用语中的同音字错误"
        },
        {
            "name": "医学术语纠错",
            "transcript": "[spk0]: 你好，请问哪里不舒服？\n[spk1]: 医生，我有搞血压，已经三年了。\n[spk0]: 有没有吃过药？\n[spk1]: 吃过阿莫希林。\n[spk0]: 那个不是降压药。我给您开点降压药。",
            "expected_corrections": ["搞血压" → "高血压", "阿莫希林" → "阿莫西林"],
            "description": "测试医学术语中的拼音相似错误"
        },
        {
            "name": "同音字混淆纠错",
            "transcript": "[spk0]: 你有什么症状？\n[spk1]: 我一直刻嗽，还有点发骚。\n[spk0]: 咳嗽多久了？\n[spk1]: 大概一周了。\n[spk0]: 有没有痰？\n[spk1]: 没有。",
            "expected_corrections": ["刻嗽" → "咳嗽", "发骚" → "发烧"],
            "description": "测试同音字混淆错误"
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{'=' * 80}")
        print(f"测试案例 {i}: {test_case['name']}")
        print(f"{'=' * 80}")
        print(f"描述: {test_case['description']}")
        print(f"\n原始对话:")
        print(test_case['transcript'])
        print(f"\n预期纠正:")
        for correction in test_case['expected_corrections']:
            print(f"  - {correction}")
        
        extracted_data = {
            "subjective": {
                "chief_complaint": {"value": "头疼", "evidence_ids": [1]},
                "history_present_illness": {"value": "头疼三天", "evidence_ids": [1, 3]}
            },
            "objective": {
                "physical_examination": {"value": "血压145/95mmHg", "evidence_ids": [7]}
            },
            "assessment": {
                "diagnosis": {"value": "高血压", "evidence_ids": [8]}
            },
            "plan": {
                "treatment": {"value": "降压药", "evidence_ids": [9]},
                "advice": {"value": "少吃闲的食物，多休息", "evidence_ids": [9]}
            }
        }
        
        template_requirements = """
        生成符合中国医疗病历书写规范的SOAP格式病历。
        使用规范的医学术语。
        """
        
        prompt = prompt_manager.render(
            "emr_generation_with_role",
            transcript=test_case['transcript'],
            extracted_data=json.dumps(extracted_data, ensure_ascii=False, indent=2),
            template_requirements=template_requirements
        )
        
        print(f"\n{'=' * 80}")
        print("提示词片段（纠错部分）:")
        print(f"{'=' * 80}")
        lines = prompt.split('\n')
        for j, line in enumerate(lines):
            if '纠正ASR转写错误' in line:
                print('\n'.join(lines[j:j+15]))
                break
        
        print(f"\n{'=' * 80}")
        print("发送给LLM...")
        print(f"{'=' * 80}")
        
        try:
            response = llm_service.call_llm(prompt)
            
            if response:
                print("\nLLM响应:")
                print(response[:500] + "..." if len(response) > 500 else response)
                
                try:
                    result = json.loads(response[response.find('{'):response.rfind('}')+1])
                    
                    print(f"\n{'=' * 80}")
                    print("解析后的病历:")
                    print(f"{'=' * 80}")
                    
                    if 'subjective' in result:
                        print(f"\n主观部分:")
                        print(f"  {result['subjective'].get('text', 'N/A')}")
                    
                    if 'objective' in result:
                        print(f"\n客观部分:")
                        print(f"  {result['objective'].get('text', 'N/A')}")
                    
                    if 'assessment' in result:
                        print(f"\n评估:")
                        print(f"  {result['assessment'].get('text', 'N/A')}")
                    
                    if 'plan' in result:
                        print(f"\n计划:")
                        print(f"  {result['plan'].get('text', 'N/A')}")
                    
                    print(f"\n{'=' * 80}")
                    print("纠错验证:")
                    print(f"{'=' * 80}")
                    
                    plan_text = result.get('plan', {}).get('text', '')
                    advice_value = result.get('plan', {}).get('advice', {}).get('value', '')
                    
                    all_text = plan_text + ' ' + advice_value
                    
                    corrections_found = []
                    for correction in test_case['expected_corrections']:
                        wrong_word = correction.split('→')[0].strip('"').strip()
                        correct_word = correction.split('→')[1].strip('"').strip()
                        
                        if correct_word in all_text and wrong_word not in all_text:
                            corrections_found.append(f"✓ {correction}")
                        elif wrong_word in all_text:
                            corrections_found.append(f"✗ {correction} (未纠正)")
                        else:
                            corrections_found.append(f"? {correction} (未找到)")
                    
                    for cf in corrections_found:
                        print(f"  {cf}")
                    
                except json.JSONDecodeError as e:
                    print(f"\nJSON解析失败: {e}")
            else:
                print("\nLLM未返回响应")
                
        except Exception as e:
            print(f"\n测试失败: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n{'=' * 80}")
    print("测试完成")
    print(f"{'=' * 80}")


if __name__ == "__main__":
    test_asr_correction()
