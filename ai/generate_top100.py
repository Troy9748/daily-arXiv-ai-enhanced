import json
import os
import re
import subprocess
import sys
from pathlib import Path

import requests


def call_llm_rerank(title: str, summary: str, zotero_summary: str) -> tuple:
    """读取 GitHub Secrets 中的 DeepSeek 凭证进行语义精排"""
    # 读取你配置的 Secrets 映射
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com").strip()
    
    # 💡 核心修改：将默认模型无缝切换为 DeepSeek 官方通用的 deepseek-v4-flash
    model_name = os.environ.get("OPENAI_MODEL_NAME", "deepseek-v4-flash").strip()

    if not api_key:
        return None, None

    system_prompt = (
        "你是一个资深的天体物理学家和学术论文推荐专家。你需要根据用户的 Zotero 兴趣画像，"
        "评估一篇新论文是否值得他精读，并给出深度的、一针见血的个性化推荐理由。"
    )

    user_prompt = f"""
用户的 Zotero 兴趣画像总结如下：
{zotero_summary}

请评估以下论文：
标题: {title}
摘要/TL;DR: {summary}

请严格按照以下格式回复（不要包含任何其他正文或 Markdown 嵌套）：
SCORE: <请根据语义相关度给出 60-95 之间的整数分，越契合你研究方向的分数越高>
REASON: <请用中文一句话一针见血地指出，这篇论文从物理创新、方法学或观测设备上，对用户的学术研究有什么具体的潜在启发或参考价值。不要说空话套话。>
"""

    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
        }
        
        url = f"{base_url.rstrip('/')}/chat/completions"
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        content = result["choices"][0]["message"]["content"].strip()

        score_match = re.search(r"SCORE:\s*(\d+)", content)
        reason_match = re.search(r"REASON:\s*(.*)", content)

        score = int(score_match.group(1)) if score_match else None
        reason = reason_match.group(1).strip() if reason_match else None
        return score, reason
    except Exception as e:
        print(f"DeepSeek API 调用失败或解析错误: {e}", file=sys.stderr)
        return None, None


def main():
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = repo_root / "data"
    profile_path = data_dir / "zotero_profile.json"

    zotero_summary = "天体物理学相关研究"
    if profile_path.exists():
        try:
            with open(profile_path, "r", encoding="utf-8") as f:
                prof = json.load(f)
                zotero_summary = prof.get("summary", zotero_summary)
        except Exception:
            pass

    # 1. 搜集所有历史 AI 增强的 jsonl 文件
    all_papers = []
    language = os.environ.get("LANGUAGE", "").strip()
    pattern = f"*_AI_enhanced_{language}.jsonl" if language else "*_AI_enhanced_*.jsonl"

    for path in data_dir.glob(pattern):
        if "top_100" in path.name:
            continue
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    all_papers.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    if not all_papers:
        print("没有找到任何历史论文数据。", file=sys.stderr)
        return

    # 2. 粗排
    all_papers.sort(
        key=lambda x: (
            x.get("recommendation", {}).get("score", 0),
            x.get("id", ""),
        ),
        reverse=True,
    )

    # 3. 截取前 100 篇
    top_100_papers = all_papers[:100]
    has_llm = "OPENAI_API_KEY" in os.environ

    if has_llm:
        print(f"正在使用 DeepSeek 对前 {len(top_100_papers)} 篇高分论文进行语义精排与理由重写...")
    else:
        print("未检测到有效密钥，将自动使用原有的规则推荐理由生成榜单。")

    # 4. 精排：调用大模型
    for idx, paper in enumerate(top_100_papers):
        rec = paper.get("recommendation", {})

        if has_llm:
            title = paper.get("title", "")
            summary = paper.get("AI", {}).get("tldr", "") if isinstance(paper.get("AI"), dict) else paper.get("summary", "")

            llm_score, llm_reason = call_llm_rerank(title, summary, zotero_summary)

            if llm_score and llm_reason:
                rec["score"] = llm_score
                rec["reason"] = llm_reason
                rec["stars"] = max(1, min(5, math.ceil(llm_score / 20)))
                paper["recommendation"] = rec
                print(f"[{idx+1}/100] 成功通过 DeepSeek 增强: {title[:40]}...")
            else:
                print(f"[{idx+1}/100] DeepSeek 未返回有效结果，保留原规则分数。")

    # 5. 二次重排
    top_100_papers.sort(
        key=lambda x: (
            x.get("recommendation", {}).get("score", 0),
            x.get("id", ""),
        ),
        reverse=True,
    )

    # 6. 保存最终文件
    top_100_jsonl = data_dir / "top_100_AI_enhanced.jsonl"
    with top_100_jsonl.open("w", encoding="utf-8") as f:
        for item in top_100_papers:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    # 7. 渲染
    convert_script = repo_root / "to_md" / "convert.py"
    if convert_script.exists():
        subprocess.run(
            [sys.executable, str(convert_script), "--data", str(top_100_jsonl)],
            cwd=repo_root / "to_md",
            check=True,
        )
        print("🎉 Top 100 DeepSeek 精排榜单已成功刷新并生成！")


if __name__ == "__main__":
    import math
    main()
