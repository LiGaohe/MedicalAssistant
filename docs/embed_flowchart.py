import base64
import re

svg_path = 'd:/practice/MedicalAssisstant/docs/系统总体流程图.svg'
html_path = 'd:/practice/MedicalAssisstant/docs/汇报-2.html'

with open(svg_path, 'r', encoding='utf-8') as f:
    svg_content = f.read()

svg_base64 = base64.b64encode(svg_content.encode('utf-8')).decode('ascii')
data_url = f"data:image/svg+xml;base64,{svg_base64}"

with open(html_path, 'r', encoding='utf-8') as f:
    html_content = f.read()

old_flow_diagram = '''<div class="flow-diagram">
                <div class="flow-steps">
                    <div class="flow-step">医疗ASR</div>
                    <span class="flow-arrow">→</span>
                    <div class="flow-step">术语纠错与标准化</div>
                    <span class="flow-arrow">→</span>
                    <div class="flow-step">结构化病历生成</div>
                    <span class="flow-arrow">→</span>
                    <div class="flow-step">错误检测与回写</div>
                </div>
            </div>'''

new_content = f'''<div class="flow-diagram">
                <img src="{data_url}" alt="系统总体流程图" style="max-width: 100%; border: 1px solid #ccc; background: #fefcf7; padding: 0.5rem;">
            </div>'''

html_content = html_content.replace(old_flow_diagram, new_content)

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html_content)

print("系统总体流程图已成功嵌入HTML为Base64格式！")
