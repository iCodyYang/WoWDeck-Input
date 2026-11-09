"""Input-transparent dictation capsule. stdin carries only levels and display states."""
import json
import math
import os
import subprocess
import sys
import time
import re

from game import focused_game, xcommand
from waveform import BAR_COUNT, ERROR_LABELS, bar_rect, bar_settings


def draw_wave(cr, levels, w, h, opacity, phase='recording', failure='输入失败'):
    import cairo
    cr.set_operator(cairo.OPERATOR_SOURCE)
    cr.set_source_rgba(0, 0, 0, 0)
    cr.paint()
    cr.set_operator(cairo.OPERATOR_OVER)
    cr.push_group()

    radius = max(1, h/2-2)
    cr.new_sub_path()
    cr.arc(w-radius-2, h/2, radius, -math.pi/2, math.pi/2)
    cr.arc(radius+2, h/2, radius, math.pi/2, 3*math.pi/2)
    cr.close_path()
    cr.set_source_rgba(.055, .067, .079, .94)
    cr.fill_preserve()
    cr.set_source_rgba(.82, .88, .89, .72)
    cr.set_line_width(max(1.25, h*.031))
    cr.stroke()
    cr.set_line_cap(cairo.LINE_CAP_ROUND)

    if phase == 'recording':
        pitch = (w*.66)/BAR_COUNT
        for i, level in enumerate(levels):
            x = w*.17 + pitch*(i+.5)
            rise = .5 + level*h*.24
            tint = max(0.0, (level-.4)/.6)
            cr.set_source_rgb(.97-.35*tint, .99, 1-.1*tint)
            cr.set_line_width(pitch*.50)
            cr.move_to(x, h/2-rise)
            cr.line_to(x, h/2+rise)
            cr.stroke()
    else:
        import gi
        gi.require_version('PangoCairo', '1.0')
        from gi.repository import Pango, PangoCairo
        label = {'recognizing':'正在转写', 'error':failure, 'done':'请检查文字','cancelled':'已取消'}[phase]
        layout = PangoCairo.create_layout(cr)
        font = Pango.FontDescription.from_string('Sans Medium')
        font.set_absolute_size(max(12, h*.34)*Pango.SCALE)
        layout.set_font_description(font)
        layout.set_text(label, -1)
        tw, th = layout.get_pixel_size()
        r = h*.095
        gap = h*.18
        left = (w-(2*r+gap+tw))/2
        cr.set_source_rgb(*((1, .60, .53) if phase=='error' else (.72,.76,.80) if phase=='cancelled' else (.64, .95, .88)))
        if phase == 'recognizing':
            angle = time.monotonic()*4.5
            cr.set_line_width(max(1.5, h*.048))
            cr.arc(left+r, h/2, r, angle, angle+math.pi*1.45)
            cr.stroke()
        else:
            cr.arc(left+r, h/2, r*.8, 0, math.tau)
            cr.fill()
        cr.set_source_rgb(.96, .98, .99)
        cr.move_to(left+2*r+gap, (h-th)/2)
        PangoCairo.show_layout(cr, layout)
    cr.pop_group_to_source()
    cr.paint_with_alpha(opacity)


def run(target, style):
    root_display = os.environ['DISPLAY']
    os.environ.update(DISPLAY=target[0], WDI_ROOT_DISPLAY=root_display, GDK_BACKEND='x11')
    import cairo
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('GdkX11', '3.0')
    from gi.repository import GdkX11, GLib, Gtk

    # An explicitly opened Steam keyboard may still be handing focus back to WoW.
    for _ in range(12):
        if focused_game() == target:
            break
        time.sleep(.045)
    else:
        return
    window = Gtk.Window(type=Gtk.WindowType.POPUP, title='WoWDeck Voice Wave')
    window.set_wmclass('WowDeckVoiceWave', 'WowDeckVoiceWave')
    window.set_decorated(False)
    window.set_accept_focus(False)
    window.set_focus_on_map(False)
    window.set_skip_taskbar_hint(True)
    window.set_skip_pager_hint(True)
    window.set_app_paintable(True)
    screen = window.get_screen()
    visual = screen.get_rgba_visual()
    if not visual:
        raise RuntimeError('透明波形窗口不可用')
    window.set_visual(visual)
    display = screen.get_display()
    game = GdkX11.X11Window.foreign_new_for_display(display, int(target[1]))
    if not game:
        return
    _, ox, oy = game.get_origin()
    x, y, w, h = bar_rect(game.get_width(), game.get_height(), style)
    window.set_size_request(w, h)
    window.resize(w, h)
    window.move(ox+x, oy+y)
    window.realize()
    surface = window.get_window()
    surface.set_override_redirect(True)
    surface.set_pass_through(True)
    surface.input_shape_combine_region(cairo.Region(), 0, 0)
    display.flush()
    # These are Wine decoration flags (no activate, layered, transparent).
    # Never claim Steam's overlay, notification, or input-focus plane.
    xid = str(surface.get_xid())
    for key, value in [('STEAM_GAME', target[2]), ('_WINE_HWND_EXSTYLE', str(0x08080020))]:
        subprocess.run(['xprop','-id',xid,'-f',key,'32c','-set',key,value],
                       check=True, timeout=1, stdout=subprocess.DEVNULL)
    levels = [0.0] * BAR_COUNT
    opened = time.monotonic()
    phase = 'recording'
    failure = '输入失败'
    deadline = opened+50
    lost_focus = None
    pending = bytearray()
    os.set_blocking(sys.stdin.fileno(), False)
    def receive(source, flags):
        nonlocal levels, phase, deadline, failure
        if flags & (GLib.IO_HUP | GLib.IO_ERR):
            Gtk.main_quit()
            return False
        data = os.read(sys.stdin.fileno(), 8192)
        if not data:
            Gtk.main_quit()
            return False
        pending.extend(data)
        while b'\n' in pending:
            row, _, rest = pending.partition(b'\n')
            pending[:] = rest
            values = json.loads(row)
            if isinstance(values, dict):
                next_phase = values.get('phase')
                if next_phase == 'yield':
                    window.hide()
                    continue
                if next_phase in ('recognizing', 'error', 'done','cancelled'):
                    phase = next_phase
                    failure = values.get('label') if values.get('label') in ERROR_LABELS else '输入失败'
                    if phase in ('error', 'done','cancelled'):
                        deadline = time.monotonic() + (2.6 if phase=='error' else .8)
                        if not window.get_visible() and focused_game()==target:
                            window.show_all()
                continue
            if isinstance(values, list) and len(values) == BAR_COUNT and all(type(v) in (float,int) and math.isfinite(v) and 0<=v<=1 for v in values):
                levels = values
        window.queue_draw()
        return True
    def guard():
        nonlocal lost_focus
        # The worker also closes our pipe on key-up, loss of UI or menu entry.
        # One root query catches app changes without repeatedly inspecting game processes.
        props = xcommand(root_display, 'xprop', '-root', 'GAMESCOPE_FOCUSED_WINDOW', 'GAMESCOPE_FOCUSED_APP')
        ids = dict(re.findall(r'^(\w+)\(CARDINAL\) = (\d+)', props, re.MULTILINE))
        now = time.monotonic()
        if ids.get('GAMESCOPE_FOCUSED_WINDOW') == target[1] and ids.get('GAMESCOPE_FOCUSED_APP') == target[2]:
            lost_focus = None
        elif lost_focus is None:
            lost_focus = now
        # The parent closes the window on release/menu entry, even if the mic has
        # not sent its first frame yet. A transient focus update should not flash it.
        if now >= deadline or (lost_focus is not None and now-lost_focus >= .45):
            Gtk.main_quit()
            return False
        return True
    def draw(_, cr):
        draw_wave(cr, levels, w, h, style['opacity'], phase, failure)
        return True
    def animate():
        if phase == 'recognizing': window.queue_draw()
        return True
    GLib.timeout_add(100, animate)
    window.connect('draw', draw)
    GLib.io_add_watch(sys.stdin.fileno(), GLib.PRIORITY_DEFAULT,
                      GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, receive)
    GLib.timeout_add(300, guard)
    if focused_game() == target:
        window.show_all()
        surface.set_pass_through(True)
        window.queue_draw()
        Gtk.main()
    window.destroy()


if __name__ == '__main__':
    if os.geteuid() == 0:
        sys.exit(1)
    args = json.loads(sys.argv[1])
    run(tuple(args['target']), bar_settings(args['style']))
