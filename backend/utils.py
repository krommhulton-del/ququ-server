"""通用小工具:JSON 健壮提取、目录辅助、时间戳。"""
import json
import re
from datetime import datetime
from pathlib import Path


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def extract_json(text: str):
    """从模型输出中提取 JSON 对象:剥代码块围栏与前后杂文,失败抛 ValueError。"""
    if not text or not text.strip():
        raise ValueError("空输出")
    text = text.strip()
    # 剥掉 ```json ... ``` 围栏
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 截取首尾花括号之间(兼容模型在 JSON 前后加解释文字)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("输出中找不到合法 JSON")
