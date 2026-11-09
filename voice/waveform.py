"""Display preferences and a short RMS history built from the captured 16 kHz mono PCM."""
import array
import math
import sys
from collections import deque

DEFAULT_BAR = {'x': 0.5, 'y': 0.82, 'opacity': 0.90}
BAR_COUNT = 17
FRAME_BYTES = 1280  # 40 ms of signed 16-bit samples

ERROR_LABELS = ('输入失败','连接超时','连接失败','识别超时','未识别到声音','请重新登录','填入失败')


def error_label(message):
    if '登录' in message or '扫码' in message: return '请重新登录'
    if '连接超时' in message: return '连接超时'
    if '没有返回结果' in message or '完整的识别结果' in message or '听写超时' in message: return '识别超时'
    if '网络' in message or '连接中断' in message or '连接失败' in message: return '连接失败'
    if '麦克风' in message or '静音' in message or '没有识别到文字' in message: return '未识别到声音'
    if '填入' in message or '粘贴' in message: return '填入失败'
    return '输入失败'


def bar_settings(value):
    if not isinstance(value, dict):
        raise ValueError('波形框设置无效')
    result = {}
    for key, default in DEFAULT_BAR.items():
        number = value.get(key, default)
        if type(number) not in (int, float) or not math.isfinite(number):
            raise ValueError('波形框设置无效')
        result[key] = max(0.2 if key == 'opacity' else 0.0, min(1.0, number))
    return result


class WaveMeter:
    def __init__(self):
        self.pending = bytearray()
        self.history = deque([0.0] * BAR_COUNT, maxlen=BAR_COUNT)

    def feed(self, pcm):
        self.pending.extend(pcm)
        updated = False
        while len(self.pending) >= FRAME_BYTES:
            samples = array.array('h', self.pending[:FRAME_BYTES])
            del self.pending[:FRAME_BYTES]
            if sys.byteorder != 'little':
                samples.byteswap()
            rms = math.sqrt(sum(v*v for v in samples) / len(samples)) / 32768
            # Map -52 to -10 dBFS to the displayed height. Silence stays flat.
            level = max(0.0, min(1.0, (20*math.log10(max(rms, 0.00001))+52)/42))
            self.history.append(round(level, 3))
            updated = True
        return list(self.history) if updated else None


def bar_rect(width, height, style):
    w = min(width, max(118, min(216, round(width * 0.145))))
    h = min(height, max(32, round(w * 0.25)))
    return round((width-w)*style['x']), round((height-h)*style['y']), w, h
