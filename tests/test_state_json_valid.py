"""守护 STATE.json 永远是合法 JSON。

事故记录:current_milestone 里被字面写入裸双引号(如 用户授权"..."),文件坏了
很多轮才被首次 json.load 暴露。此测试让每次回归自动抓。
"""
import json
from pathlib import Path

STATE = Path(__file__).resolve().parent.parent / "STATE.json"


def test_state_json_is_valid():
    data = json.loads(STATE.read_text(encoding="utf-8"))
    assert data["project"] == "flipped"
    assert isinstance(data["current_milestone"], str) and data["current_milestone"]
    assert isinstance(data["milestones"], dict)
