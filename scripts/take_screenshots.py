"""
截图脚本：获取系统界面截图用于科创经历证明材料
"""
import time
import os
from playwright.sync_api import sync_playwright

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "docs", "提交", "screenshots")
os.makedirs(OUTPUT_DIR, exist_ok=True)

BASE_URL = "http://localhost:8000"

def take_screenshots():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        # 1. 主界面（上传页面）
        print("截图1: 主界面...")
        page.goto(BASE_URL, wait_until="networkidle")
        page.screenshot(path=os.path.join(OUTPUT_DIR, "01_main_page.png"), full_page=True)
        print("  -> 已保存 01_main_page.png")

        # 2. 病历生成页面（emr.html）
        print("截图2: 病历生成界面...")
        page.goto(f"{BASE_URL}/static/emr.html", wait_until="networkidle")
        time.sleep(1)
        page.screenshot(path=os.path.join(OUTPUT_DIR, "02_emr_page.png"), full_page=True)
        print("  -> 已保存 02_emr_page.png")

        # 3. 评估页面
        print("截图3: 评估界面...")
        page.goto(f"{BASE_URL}/static/evaluation.html", wait_until="networkidle")
        time.sleep(1)
        page.screenshot(path=os.path.join(OUTPUT_DIR, "03_evaluation_page.png"), full_page=True)
        print("  -> 已保存 03_evaluation_page.png")

        browser.close()
        print("所有截图完成！")

if __name__ == "__main__":
    take_screenshots()
