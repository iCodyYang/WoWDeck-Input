-- From the repo root: lua tests/draft_clear.lua (or pandoc lua tests/draft_clear.lua).
local temporaryHook, listener
local active, focus, clock, tab, mods = nil, nil, 0, 1, {}
local restricted = {}

function IsShiftKeyDown() return mods.shift end
function IsControlKeyDown() return mods.ctrl end
function IsAltKeyDown() return mods.alt end
function GetTime() return clock end
function GetCurrentKeyBoardFocus() return focus end
function FCFDock_GetSelectedWindow() return tab end
function issecretvalue(value) return value == restricted end
ChatFrameUtil = { GetActiveWindow = function() return active end }
local selectedTabHook

function CreateFrame(kind, name, parent)
    assert(kind == "Frame" and not name and not parent, "no visible toolbar or button may be created")
    assert(not listener, "only one event listener is needed")
    local frame = { scripts = {} }
    function frame:SetScript(event, fn) self.scripts[event] = fn end
    function frame:RegisterEvent(event) self.event = event end
    function frame:UnregisterEvent() self.event = nil end
    listener = frame
    return frame
end
function hooksecurefunc(name, fn)
    if name == "FCF_OpenTemporaryWindow" then temporaryHook = fn
    elseif name == "FCFDock_SelectWindow" then selectedTabHook = fn
    else error("unexpected hook") end
end

local function ChatBox()
    local box = { scripts = {}, text = "", writes = 0, visible = true }
    function box:HookScript(event, fn)
        assert(self.scripts[event] == nil, "duplicate hook")
        self.scripts[event] = fn
    end
    function box:IsForbidden() return self.forbidden end
    function box:GetFrameLevel() return 5 end
    function box:IsVisible() return self.visible end
    function box:HasFocus() return self == focus end
    function box:GetChatType() return self.channel or "SAY" end
    function box:GetTellTarget() return self.recipient end
    function box:GetChannelTarget() return 0 end
    function box:HasText() return self.secret and restricted or self.text ~= "" end
    function box:SetText(text)
        self.text, self.writes = text, self.writes + 1
        self.scripts.OnTextChanged(self)
    end
    return box
end

local first, other = ChatBox(), ChatBox()
CHAT_FRAMES = { "ChatFrame1" }
ChatFrame1 = { editBox = first }
local source = arg and arg[1] or "companion/WoWDeckDraft/WoWDeckDraft.lua"
dofile(source)
listener.scripts.OnEvent(listener, "PLAYER_LOGIN")
CHAT_FRAMES[2], ChatFrame11 = "ChatFrame11", { editBox = other }
temporaryHook()
assert(other.scripts.OnKeyDown)

active, focus = first, first
first.text, first.channel, first.recipient = "队友 ABC，重新来。", "WHISPER", "队友"
first.scripts.OnTextChanged(first)
local function signal(box, mode)
    mods = {shift=true, ctrl=mode=="prepare", alt=mode=="clear"}
    box.scripts.OnKeyDown(box, "F11")
    mods = {}
end

-- The user's key alone never clears text. Only the marked paste and the
-- supervisor's later double-tap signal authorize a clear in this edit session.
first.scripts.OnKeyDown(first, "F7")
first.scripts.OnKeyDown(first, "F7")
signal(first, "clear")
assert(first.writes == 0)
signal(first, "prepare")
first:SetText("已有草稿 + 听写结果")
signal(first, "clear")
assert(first.text == "" and first:HasFocus())
assert(first.channel == "WHISPER" and first.recipient == "队友")
first:SetText("手打的新草稿")
signal(first, "clear")
assert(first.text == "手打的新草稿")

for _,reason in ipairs({"OnEnterPressed","OnEscapePressed","OnEditFocusLost","OnHide"}) do
    signal(first,"prepare");first:SetText("上次听写")
    first.scripts[reason](first)
    first:SetText("之后的新草稿")
    signal(first,"clear")
    assert(first.text == "之后的新草稿", reason)
end
signal(first,"prepare");first:SetText("第一标签的字")
tab=2;selectedTabHook();tab=1;selectedTabHook();signal(first,"clear")
assert(first.text == "第一标签的字")
signal(first,"prepare");first:SetText("给原来的收件人")
first.recipient="其他玩家";signal(first,"clear")
assert(first.text == "给原来的收件人")
signal(first,"prepare");clock=4;first:SetText("延迟的手动修改");signal(first,"clear")
assert(first.text == "延迟的手动修改")

signal(first,"prepare");first:SetText("还在原框")
active, focus = other, other
other:SetText("另一个框")
signal(other,"clear")
assert(first.text == "还在原框" and other.text == "另一个框")
other.secret = true
signal(other,"clear")
assert(other.text == "另一个框")
print("PASS: only the same unsent voice draft clears; submit, focus, destination and manual drafts are protected")

-- Native empty notifications and a delayed paste must keep its marker alive.
active, focus = nil, first -- keyboard focus is authoritative while chat catches up
first:SetText("")
signal(first, "prepare")
first.scripts.OnTextChanged(first)
clock = clock + 1.8
first:SetText("空通知之后才到达的粘贴")
signal(first, "clear")
assert(first.text == "", "empty pre-paste callback must not revoke the ticket")

print("PASS: no toolbar or mouse handler is created; delayed voice draft clearing remains available")
