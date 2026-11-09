"""Optional, offline Wubi 86 table. No service or system IME registration."""
from functools import lru_cache
from pathlib import Path
import re

TABLE = Path(__file__).parent/'data/wubi86/wubi86.dict.yaml'


def read_table(path):
    entries = {}
    body = False
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if line == '...':
            body = True
            continue
        if not body or not line or line.startswith('#'):
            continue
        fields = line.split('\t')
        if len(fields) < 3:
            continue
        text, code, weight = fields[:3]
        if not re.fullmatch('[a-y]{1,4}', code) or not text or any(ord(c) < 32 for c in text):
            continue
        entries.setdefault(code, []).append((text, int(weight)))
    if len(entries) < 1000:
        raise ValueError('五笔词库不完整，请重新安装插件')
    return {code: list(dict.fromkeys(text for text, _ in sorted(rows, key=lambda row: -row[1])))
            for code, rows in entries.items()}


@lru_cache(maxsize=1)
def table():
    # Deliberately lazy: full pinyin, Xiaohe and voice never read this file.
    return read_table(TABLE)
