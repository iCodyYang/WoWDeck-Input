// @ts-nocheck
import {getConfig,saveAppearance,hotkeyLabel} from "../config";
// Cody: keep Steam's IME and physical key mapping; move the measured panel itself.
export const SetCandidateDisplay = (dom, physical, updateWindow = () => {}) => {
    const doc = dom.ownerDocument;
    const panel = dom.firstElementChild;
    dom.__codyCandidateObserver?.disconnect();
    dom.dataset.codyPhysical = String(physical);
    let style = doc.getElementById('cody-keyboard-display-style');
    if (!style) {
        style = doc.createElement('style');
        style.id = 'cody-keyboard-display-style';
        doc.head.appendChild(style);
    }
    style.textContent = `
[id="virtual keyboard"][data-cody-physical="true"] { visibility: visible !important; pointer-events: none !important; }
[id="virtual keyboard"][data-cody-physical="true"] > [role="grid"] { position: fixed !important; left: var(--cody-candidate-x,12px) !important; top: var(--cody-candidate-y,80px) !important; right: auto !important; bottom: auto !important; transform: none !important; overflow: visible !important; width: max-content !important; max-width: calc(100vw - 12px) !important; min-width: 0 !important; min-height: 0 !important; height: auto !important; margin: 0 !important; padding: 3px !important; visibility: visible !important; background: transparent !important; border-radius: 6px !important; pointer-events: auto !important; }
[id="virtual keyboard"][data-cody-physical="true"][data-cody-candidates="false"][data-cody-adjusting="false"] > [role="grid"] { visibility: hidden !important; }
[id="virtual keyboard"][data-cody-physical="true"] > [role="grid"] > [aria-rowindex] { display: none !important; }
[id="virtual keyboard"][data-cody-physical="true"] .Row_IME { position: static !important; left: auto !important; top: auto !important; right: auto !important; bottom: auto !important; display: flex !important; width: auto !important; height: auto !important; min-height: 0 !important; margin: 0 !important; gap: 3px; opacity: var(--cody-candidate-opacity,.95); background: rgba(25,25,25,.96); border-radius: 4px; font-size: calc(18px * var(--cody-candidate-scale,.85)) !important; }
[id="virtual keyboard"][data-cody-physical="true"] .Row_IME * { font-size: inherit !important; line-height: 1.25 !important; }
[id="virtual keyboard"][data-cody-physical="true"] .Row_IME > div { flex: 0 0 auto !important; width: auto !important; min-width: 0 !important; height: auto !important; min-height: 0 !important; }
[id="virtual keyboard"][data-cody-physical="true"] .Row_IME [data-key] { display: flex !important; align-items: center; gap: 4px; padding: calc(3px * var(--cody-candidate-scale,.85)) calc(7px * var(--cody-candidate-scale,.85)) !important; }
[id="virtual keyboard"][data-cody-physical="true"] .Row_IME [data-key] > div { padding: 0 !important; min-height: 0 !important; height: auto !important; }
[id="virtual keyboard"][data-cody-physical="true"] .Row_IME [data-cody-number]::before { content: attr(data-cody-number); color: #aaa; font-size: .78em; }
[id="virtual keyboard"][data-cody-physical="true"] .Row_IME svg { width: 18px !important; height: 18px !important; }
[id="virtual keyboard"][data-cody-physical="true"] .Row_IME img { display: none !important; }
.cody-candidate-handle { display: none; }
[id="virtual keyboard"][data-cody-physical="true"][data-cody-adjusting="true"] .cody-candidate-handle { display: flex; position: absolute; bottom: calc(100% + 6px); left: var(--cody-tools-x,0px); align-items: center; justify-content: space-between; gap: 8px; min-width: 470px; height: 28px; padding: 0 5px; font: 12px sans-serif; color: #ddd; background: #303238; border-radius: 6px 6px 0 0; cursor: grab; touch-action: none; user-select: none; }
[id="virtual keyboard"][data-cody-tools-below="true"] .cody-candidate-handle { bottom: auto; top: calc(100% + 6px); }
.cody-candidate-handle button { color: #eee; background: #464950; border: 0; border-radius: 3px; font: inherit; padding: 2px 8px; cursor: pointer; }
.cody-candidate-handle input { width: 90px; cursor: pointer; }
`;
    let position;
    try { position = {...getConfig().appearance}; } catch (_) {}
    if (!position || !Number.isFinite(position.x) || !Number.isFinite(position.y)) {
        position = { x: 12, y: 80, locked: false };
    }
    position.scale = Number.isFinite(position.scale) ? Math.max(.65, Math.min(1.25, position.scale)) : .85;
    position.opacity = Number.isFinite(position.opacity) ? Math.max(.2, Math.min(1, position.opacity)) : .95;
    let adjusting = false;
    dom.dataset.codyAdjusting = 'false';
    const place = () => {
        dom.style.setProperty('--cody-candidate-scale', String(position.scale));
        dom.style.setProperty('--cody-candidate-opacity', String(position.opacity));
        const view = doc.defaultView;
        const width = panel.offsetWidth || Math.min(640, view.innerWidth - 24);
        position.x = Math.max(0, Math.min(position.x, view.innerWidth - width));
        position.y = Math.max(0, Math.min(position.y, view.innerHeight - Math.max(60, panel.offsetHeight)));
        dom.style.setProperty('--cody-candidate-x', position.x + 'px');
        dom.style.setProperty('--cody-candidate-y', position.y + 'px');
        const tools = panel.querySelector('.cody-candidate-handle');
        const toolWidth = tools?.offsetWidth || 490;
        const toolHeight = tools?.offsetHeight || 28;
        dom.style.setProperty('--cody-tools-x', Math.min(0, view.innerWidth - position.x - toolWidth - 6) + 'px');
        dom.dataset.codyToolsBelow = String(position.y < toolHeight + 6);
        if (physical) {
            const rect = panel.getBoundingClientRect();
            const signature = [rect.x, rect.y, rect.width, rect.height].join(',');
            if (dom.__codyCandidateRect !== signature) {
                dom.__codyCandidateRect = signature;
                updateWindow();
            }
        }
    };
    const save = () => saveAppearance({...position});
    let handle = panel.querySelector('.cody-candidate-handle');
    if (!handle) {
        handle = doc.createElement('div');
        handle.className = 'cody-candidate-handle';
        panel.prepend(handle);
    }
    handle.replaceChildren();
    const label = doc.createElement('span');
    label.textContent = '⠿ 拖动';
    const scaleText = doc.createElement('span');
    const slider = doc.createElement('input');
    slider.type = 'range'; slider.min = '65'; slider.max = '125'; slider.step = '5';
    slider.value = String(Math.round(position.scale * 100));
    slider.title = '候选框大小'; slider.setAttribute('aria-label', '候选框大小');
    const opacityText = doc.createElement('span');
    const opacitySlider = doc.createElement('input');
    opacitySlider.type = 'range'; opacitySlider.min = '0'; opacitySlider.max = '80'; opacitySlider.step = '5';
    opacitySlider.value = String(Math.round((1 - position.opacity) * 100));
    opacitySlider.title = '候选框透明度'; opacitySlider.setAttribute('aria-label', '候选框透明度');
    const hint = doc.createElement('span'); hint.textContent = hotkeyLabel(getConfig().adjust) + ' 保存';
    const updateControls = () => {
        dom.dataset.codyAdjusting = String(adjusting);
        const text = '大小 ' + Math.round(position.scale * 100) + '%';
        if (scaleText.textContent !== text) scaleText.textContent = text;
        const opacityLabel = '透明度 ' + Math.round((1 - position.opacity) * 100) + '%';
        if (opacityText.textContent !== opacityLabel) opacityText.textContent = opacityLabel;
        position.locked = !adjusting;
    };
    const toggleAdjusting = () => { adjusting = !adjusting; updateControls(); place(); save(); };
    dom.__codyToggleAdjustment = toggleAdjusting;
    handle.append(label, scaleText, slider, opacityText, opacitySlider, hint);
    updateControls();
    for (const control of [slider, opacitySlider]) control.onpointerdown = event => event.stopPropagation();
    slider.oninput = event => { event.stopPropagation(); position.scale = Number(slider.value) / 100; updateControls(); place(); save(); };
    opacitySlider.oninput = event => { event.stopPropagation(); position.opacity = 1 - Number(opacitySlider.value) / 100; updateControls(); place(); save(); };
    let drag = null;
    handle.onpointerdown = event => {
        if (!adjusting || event.target.closest('button,input') || event.button > 0) return;
        event.preventDefault(); event.stopPropagation();
        drag = { x: event.clientX, y: event.clientY, startX: position.x, startY: position.y };
        handle.setPointerCapture(event.pointerId);
    };
    handle.onpointermove = event => {
        if (!drag) return;
        event.preventDefault(); event.stopPropagation();
        position.x = drag.startX + event.clientX - drag.x;
        position.y = drag.startY + event.clientY - drag.y;
        place();
    };
    handle.onpointerup = handle.onpointercancel = event => {
        if (!drag) return;
        event.preventDefault(); event.stopPropagation();
        drag = null; save();
        if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
    };
    const updateCandidates = () => {
        const candidates = dom.querySelectorAll('.Row_IME [data-key^="IME_LUT_Select_"]');
        candidates.forEach(key => {
            const number = Number(key.getAttribute('data-key').split('_').pop()) + 1;
            if (key.dataset.codyNumber !== String(number)) key.dataset.codyNumber = String(number);
        });
        const visible = Array.from(candidates).some(key => key.textContent.trim().length > 0);
        const value = String(visible);
        if (dom.dataset.codyCandidates !== value) dom.dataset.codyCandidates = value;
        updateControls();
        place();
    };
    updateCandidates();
    if (physical) {
        dom.__codyCandidateObserver = new MutationObserver(updateCandidates);
        dom.__codyCandidateObserver.observe(dom, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['class'] });
    }
};
