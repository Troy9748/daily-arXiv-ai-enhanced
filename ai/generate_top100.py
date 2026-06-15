import json
import os
import subprocess
import sys
from pathlib import Path

def main():
    # 定位路径
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = repo_root / "data"
    
    # 1. 搜集所有历史 AI 增强的 jsonl 文件（排除掉 top_100 本身）
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
                    item = json.loads(line)
                    all_papers.append(item)
                except json.JSONDecodeError:
                    continue

    if not all_papers:
        print("没有找到任何历史论文数据。", file=sys.stderr)
        return

    # 2. 全局排序：按 score 降序排列，score 相同按 id 排
    all_papers.sort(
        key=lambda x: (
            x.get("recommendation", {}).get("score", 0),
            x.get("id", ""),
        ),
        reverse=True,
    )

    # 3. 截取前 100 篇
    top_100_papers = all_papers[:100]
    print(f"成功从 {len(all_papers)} 篇历史论文中筛选出 Top 100。")

    # 4. 写入一个专用的 Top 100 jsonl 文件
    top_100_jsonl = data_dir / "top_100_AI_enhanced.jsonl"
    with top_100_jsonl.open("w", encoding="utf-8") as f:
        for item in top_100_papers:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    # 5. 调用你原有的 convert.py，将其渲染为网页 Markdown 文件
    convert_script = repo_root / "to_md" / "convert.py"
    if convert_script.exists():
        subprocess.run(
            [sys.executable, str(convert_script), "--data", str(top_100_jsonl)],
            cwd=repo_root / "to_md",
            check=True,
        )
        print("已成功调用 convert.py 生成 Top 100 Markdown 页面。")
    else:
        print(f"未找到转换脚本: {convert_script}，请检查路径。", file=sys.stderr)

if __name__ == "__main__":
    main()
