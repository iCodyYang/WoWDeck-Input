// @ts-nocheck
// Physical key mapping adapted from Chenx Dust/BetterKeyboard, BSD-3-Clause.
import {EvdevToKey,GetDigitFromCode,GetPosFromKey,KeyToEvdev} from "./map";
const SHORT_CLICK_TIMEOUT=250;
export const CreateRawKeyboardListener = (ctx) => (code, value) => {
    if (value === 1 && code !== KeyToEvdev.ShiftLeft && code !== KeyToEvdev.ShiftRight)
        ctx.shortClickShiftCode = null;
    // Special Keys
    const checkAltGr = () => {
        if (ctx.dom?.querySelector('div[data-key="AltGr"]') === null)
            return;
        ctx.component?.setState(((e, _) => ({
            ...e,
            toggleStates: {
                ...e.toggleStates,
                AltGr: Math.min(e.toggleStates?.Alt || 0, e.toggleStates?.Control || 0),
            }
        })));
    };
    if (code == KeyToEvdev.ShiftLeft || code == KeyToEvdev.ShiftRight) {
        if (value >= 2)
            return; // ignore auto-repeat
        ctx.component?.setState(((e, _) => ({
            ...e,
            toggleStates: {
                ...e.toggleStates,
                Shift: value === 0 ? 0 : 2,
            }
        })));
        if (value === 1) {
            ctx.shortClickShiftCode = code;
            setTimeout(() => {
                if (ctx.shortClickShiftCode === code) ctx.shortClickShiftCode = null;
            }, SHORT_CLICK_TIMEOUT);
            return;
        }
    }
    else if (code == KeyToEvdev.ControlLeft || code == KeyToEvdev.ControlRight) {
        if (value >= 2)
            return; // ignore auto-repeat
        ctx.component?.setState(((e, _) => ({
            ...e,
            toggleStates: {
                ...e.toggleStates,
                Control: value === 0 ? 0 : 2,
            }
        })));
        checkAltGr();
        return;
    }
    else if (code == KeyToEvdev.AltLeft || code == KeyToEvdev.AltRight) {
        if (value >= 2)
            return; // ignore auto-repeat
        ctx.component?.setState(((e, _) => ({
            ...e,
            toggleStates: {
                ...e.toggleStates,
                Alt: value === 0 ? 0 : 2,
            }
        })));
        checkAltGr();
        return;
    }
    else if (code == KeyToEvdev.CapsLock && value === 1) {
        ctx.component?.setState(((e, _) => ({
            ...e,
            toggleStates: {
                ...e.toggleStates,
                CapsLock: e.toggleStates.CapsLock === 0 ? 2 : 0,
            }
        })));
        return;
    }
    // Normal Keys
    let ev = {
        strKey: "",
        strKeycode: "",
    };
    const hasIntlBackslash = ctx.dom?.querySelector(`div[data-key-row="3"][data-key-col="12"]`) !== null;
    const pos = GetPosFromKey(code, hasIntlBackslash);
    if (value == 0) {
        if ((code == KeyToEvdev.ShiftLeft || code == KeyToEvdev.ShiftRight) && ctx.shortClickShiftCode === code) {
            ctx.shortClickShiftCode = null;
            ev.strKey = "SwitchKeys_Layout";
        }
        else
            return;
    }
    else if (code == KeyToEvdev.Space) {
        // default to " " because Steam uses it
        ev.strKey = " ";
        // try to get the key from the selected key panel
        const selectedKey = ctx.dom?.querySelector('div.Panel.gpfocus')?.getAttribute("data-key");
        if (selectedKey?.startsWith("IME_LUT_Select_")) {
            ev.strKey = selectedKey;
        }
    }
    else if (code == KeyToEvdev.Delete) {
        ev.strKey = "\x7F";
    }
    else if (code == KeyToEvdev.Escape) {
        ev.strKey = "VKClose";
    }
    else if (code >= KeyToEvdev.Digit1 && code <= KeyToEvdev.Digit0 &&
        ctx.dom?.querySelector(`div[data-key="IME_LUT_Select_${GetDigitFromCode(code)}"]`) && // check if there is candidate key
        pos && ctx.dom?.querySelector(`div[data-key-row="${pos[0]}"][data-key-col="${pos[1]}"]`) // fix Zhuyin, etc. that uses digit key
        ?.querySelector("span:not([class])")?.innerText === GetDigitFromCode(code).toString()) {
        ev.strKey = `IME_LUT_Select_${GetDigitFromCode(code)}`;
    }
    else if ([KeyToEvdev.PageDown, KeyToEvdev.Equal, KeyToEvdev.BracketLeft].includes(code) &&
        ctx.dom?.querySelector(`div[data-key="IME_LUT_Down"]`) && // check if there is candidate key
        (pos != null ? ctx.dom?.querySelector(`div[data-key-row="${pos[0]}"][data-key-col="${pos[1]}"]`)
            ?.querySelector("span:not([class])")?.innerText === "=" : true)) { // fix Zhuyin, etc. that uses equal key
        ev.strKey = "IME_LUT_Down";
    }
    else if ([KeyToEvdev.PageUp, KeyToEvdev.Minus, KeyToEvdev.BracketRight].includes(code) &&
        ctx.dom?.querySelector(`div[data-key="IME_LUT_Up"]`) && // check if there is candidate key
        (pos != null ? ctx.dom?.querySelector(`div[data-key-row="${pos[0]}"][data-key-col="${pos[1]}"]`)
            ?.querySelector("span:not([class])")?.innerText === "-" : true)) { // fix Zhuyin, etc. that uses minus key
        ev.strKey = "IME_LUT_Up";
    }
    else if (pos !== null) {
        const key = ctx.dom?.querySelector(`div[data-key-row="${pos[0]}"][data-key-col="${pos[1]}"]`);
        ev = {
            strKey: key?.getAttribute("data-key") || undefined,
            strKeycode: key?.getAttribute("data-keycode") || undefined,
            strIsLiteral: key?.getAttribute("data-key-is-literal") || undefined,
            strKeyHandler: key?.getAttribute("data-key-handler") || undefined,
            strEmojiIndex: key?.getAttribute("data-emoji-index") || undefined,
            strEmojiTint: key?.getAttribute("data-emoji-tint") || undefined,
            strShifted: key?.getAttribute("data-key-shifted") || undefined,
            strDeadKeyNext: key?.getAttribute("data-dead-key-next") || undefined,
            strDeadKeyCombined: key?.getAttribute("data-dead-key-combined") || undefined,
        };
    }
    else {
        ev.strKey = EvdevToKey[code];
        if (!ev.strKey?.startsWith("Arrow"))
            return;
    }
    ctx.component?.TypeKeyInternal(ev);
};
