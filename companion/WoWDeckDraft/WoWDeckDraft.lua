local attached = {}

-- A ticket belongs to one uninterrupted edit session. Store no chat text.
local ticket
local function Focused(box)
    if box:IsForbidden() or not box:IsVisible() or not box:HasFocus() then return false end
    -- The native active-chat pointer can lag the edit box's focus notification.
    local keyboard = GetCurrentKeyBoardFocus and GetCurrentKeyBoardFocus()
    return keyboard == box or ChatFrameUtil.GetActiveWindow() == box
end

local function HasDraft(box)
    if not Focused(box) then return false end
    local value = box:HasText()
    return not (issecretvalue and issecretvalue(value)) and value
end

local function Destination(box)
    local kind, who, channel = box:GetChatType(), box:GetTellTarget(), box:GetChannelTarget()
    if issecretvalue and (issecretvalue(kind) or issecretvalue(who) or issecretvalue(channel)) then
        return nil
    end
    return kind, who, channel, FCFDock_GetSelectedWindow(GENERAL_CHAT_DOCK)
end

local function SameDestination(box)
    if not ticket or ticket.box ~= box or not Focused(box) then return false end
    local kind, who, channel, tab = Destination(box)
    return kind ~= nil and kind == ticket.kind and who == ticket.who
        and channel == ticket.channel and tab == ticket.tab
end

local function Forget(box)
    if ticket and ticket.box == box then ticket = nil end
end

local function OnKey(box, key)
    if key ~= "F10" and key ~= "F11" then return end
    if not IsShiftKeyDown() then return end
    if IsControlKeyDown() and not IsAltKeyDown() then
        ticket = nil
        if Focused(box) then
            local kind, who, channel, tab = Destination(box)
            if kind then
                ticket = {box=box, kind=kind, who=who, channel=channel, tab=tab, untilTime=GetTime()+3}
            end
        end
    elseif IsAltKeyDown() and not IsControlKeyDown() then
        local clear = ticket and ticket.filled and SameDestination(box) and HasDraft(box)
        ticket = nil
        if clear then box:SetText("") end
    end
end

local function Attach(box)
    if not box or attached[box] or box:IsForbidden() then return end
    attached[box] = true
    local function Lost() Forget(box) end
    box:HookScript("OnTextChanged", function()
        if ticket and ticket.box == box then
            if not SameDestination(box) then
                ticket = nil
            elseif not ticket.filled then
                -- Empty native/IME notifications can precede clipboard text.
                -- Keep the pending marker; never authorize a clear until filled.
                if GetTime() > ticket.untilTime then ticket = nil
                elseif HasDraft(box) then ticket.filled = true end
            elseif not HasDraft(box) then
                ticket = nil
            end
        end
    end)
    box:HookScript("OnEditFocusLost", Lost)
    box:HookScript("OnHide", Lost)
    box:HookScript("OnEnterPressed", function() Forget(box) end)
    box:HookScript("OnEscapePressed", function() Forget(box) end)
    box:HookScript("OnKeyDown", OnKey)
end

local function AttachChatWindows()
    for _, name in ipairs(CHAT_FRAMES) do
        local frame = _G[name]
        if frame then Attach(frame.editBox) end
    end
end

local events = CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN")
events:SetScript("OnEvent", function(self, event)
    AttachChatWindows()
    if event ~= "PLAYER_LOGIN" then return end
    hooksecurefunc("FCF_OpenTemporaryWindow", AttachChatWindows)
    hooksecurefunc("FCFDock_SelectWindow", function()
        if ticket and not SameDestination(ticket.box) then ticket = nil end
    end)
    events:UnregisterEvent("PLAYER_LOGIN")
    events:RegisterEvent("UPDATE_CHAT_WINDOWS")
    events:RegisterEvent("PLAYER_ENTERING_WORLD")
end)
