"""Validated preferences and physical keyboard chord detection; no input text logs."""
import copy
from voice.waveform import DEFAULT_BAR, bar_settings
MODIFIERS={29:'Ctrl',97:'Ctrl',42:'Shift',54:'Shift',56:'Alt',100:'Alt',125:'Super',126:'Super'}
FUNCTION_CODES = dict(zip((f'F{i}' for i in range(1, 13)), [*range(59, 69), 87, 88]))
FKEYS=set(FUNCTION_CODES.values())
DEFAULTS={'version':4,'pluginEnabled':False,'enabled':False,'scheme':'full','voiceKey':'F7','voiceWanted':False,'wake':{'key':57,'mods':['Ctrl']},'adjust':{'key':66,'mods':[]},'appearance':{'x':12,'y':80,'scale':.85,'opacity':.95},'appearance_migrated':False}
DEFAULTS['voiceBar'] = DEFAULT_BAR.copy()
def validate_chord(value):
    if not isinstance(value,dict):raise ValueError('无效快捷键')
    key=value.get('key');mods=value.get('mods')
    if type(key) is not int or not 1<=key<=194 or key in MODIFIERS or key in {1,14,15,28,111}:raise ValueError('请选择字母、空格或功能键')
    if not isinstance(mods,list) or any(m not in {'Ctrl','Alt','Shift'} for m in mods):raise ValueError('支持 Ctrl、Alt、Shift 组合')
    mods=sorted(set(mods))
    if not mods and key not in FKEYS:raise ValueError('单键快捷键只支持 F1–F12；其他键请加修饰键')
    return {'key':key,'mods':mods}
def appearance(value):
    if not isinstance(value,dict):raise ValueError('无效候选框设置')
    result={}
    for name,default,low,high in [('x',12,0,16384),('y',80,0,16384),('scale',.85,.65,1.25),('opacity',.95,.2,1)]:
        v=value.get(name,default)
        if type(v) not in (int,float) or v!=v or abs(v)==float('inf'):raise ValueError('候选框参数必须是有限数字')
        result[name]=max(low,min(high,v))
    return result
def validate(value):
    c=copy.deepcopy(DEFAULTS)
    if not isinstance(value,dict):return c
    c.update({k:v for k,v in value.items() if k in c})
    if type(c['enabled']) is not bool:raise ValueError('启用状态无效')
    version = value.get('version')
    has_switches = version in (2, 3, 4)
    c['pluginEnabled'] = has_switches and value.get('pluginEnabled') is True
    c['voiceWanted'] = has_switches and value.get('voiceWanted') is True
    if c['scheme'] not in {'keep','full','xiaohe','wubi86'}:raise ValueError('输入方案无效')
    c['wake']=validate_chord(c['wake']);c['adjust']=validate_chord(c['adjust'])
    if c['wake']==c['adjust']:raise ValueError('唤醒和调整快捷键不能相同')
    key = c['voiceKey']
    if not isinstance(key, str) or key not in FUNCTION_CODES:
        key = DEFAULTS['voiceKey']
    if version != DEFAULTS['version']:
        # alpha.11 stored F5 as its default. Migrate only that release's
        # default; keep other selected keys and existing keyboard shortcuts.
        preferred = DEFAULTS['voiceKey'] if version == 3 and key == 'F5' else key
        keyboard_codes = {c['wake']['key'], c['adjust']['key']}
        key = next(candidate for candidate in (preferred, key, 'F7', *FUNCTION_CODES)
                   if FUNCTION_CODES[candidate] not in keyboard_codes)
    c['voiceKey'] = key
    c['appearance']=appearance(c['appearance']);c['version']=DEFAULTS['version']
    try: c['voiceBar'] = bar_settings(c['voiceBar'])
    except ValueError: c['voiceBar'] = DEFAULT_BAR.copy()
    return c
class Chord:
    def __init__(self):self.down=set();self.pending=False
    def event(self,code,value,chord):
        if value==2:return False
        if value==1:
            self.down.add(code)
            mods={MODIFIERS[k] for k in self.down if k in MODIFIERS}
            if code==chord['key'] and mods==set(chord['mods']):self.pending=True
            elif self.pending and code!=chord['key'] and code not in MODIFIERS:self.pending=False
        elif value==0:
            self.down.discard(code)
            if self.pending and not self.down:
                self.pending=False;return True
        return False
    def clear(self):self.down.clear();self.pending=False

def effective_scheme(values):
    if values.get('DoublePinyin','') in {'','false'}:return 'full'
    if values.get('DoublePinyin')=='true' and values.get('DoublePinyinSchema','').split()[-1:]==['5']:return 'xiaohe'
    return 'keep'
