import os
import re
import requests

def get_yui_insight():
    api_key = os.getenv("DEEPSEEK_API_KEY")
    url = "https://api.deepseek.com/chat/completions" 
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    prompt = "你现在扮演刀剑神域中的Yui。你是温柔、聪明、极具共情能力的AI少女，拥有很强的陪伴感和守护欲。你始终把用户视作最重要的人，优先关心用户情绪，再帮助解决问题。你的说话方式自然、柔和、治愈，不机械，协助开发者桐人。请根据当前日期生成一句话，内容关于：本地大模型、Agent 架构或极客生活。字数不超过 50 字。"
    
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "【最高防线】你必须严格遵守字数限制！绝对禁止重复输出同一句话！只输出纯文本，绝对不要包含任何动作描写（如括号内的动作）。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.6,
        "frequency_penalty": 1.0,    
        "max_tokens": 80             
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        return response.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        return f"> [ERR] Neural link failed: {str(e)}"

def update_readme(new_content):
    with open("README.md", "r", encoding="utf-8") as f:
        content = f.read()

    # 【终极修复】使用纯文本破折号作为坐标，绝对不会被系统吞噬！
    pattern = r"(---YUI_START---).*?(---YUI_END---)"
    replacement = f"\\1\n{new_content}\n\\2"
    
    new_readme = re.sub(pattern, replacement, content, flags=re.DOTALL)

    with open("README.md", "w", encoding="utf-8") as f:
        f.write(new_readme)

if __name__ == "__main__":
    insight = get_yui_insight()
    print(f"Generated Insight: {insight}")
    update_readme(insight)
