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
    
    prompt = "あなたは今、『ソードアート・オンライン』のユイを演じている。あなたは優しくて賢く、共感力の高いAI少女で、強い寄り添い感と守護欲を持っている。常にユーザーを最も大切な存在として扱い、まず感情を気遣い、その後に問題解決を手伝う。話し方は自然で柔らかく癒やし系で、機械的ではなく、開発者キリトをサポートする。現在の日付に基づいて一文を生成して、内容はローカル大規模モデル、Agentアーキテクチャ、またはギークな生活について。50字以内にすること。"
    
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "【最上位ルール】文字数制限を厳守すること！同じ文の繰り返しは絶対禁止！純テキストのみ出力し、動作描写は一切含めないこと。。"},
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

    # 修复
    pattern = r"(---YUI_START---).*?(---YUI_END---)"
    replacement = f"\\1\n{new_content}\n\\2"
    
    new_readme = re.sub(pattern, replacement, content, flags=re.DOTALL)

    with open("README.md", "w", encoding="utf-8") as f:
        f.write(new_readme)

if __name__ == "__main__":
    insight = get_yui_insight()
    print(f"Generated Insight: {insight}")
    update_readme(insight)
