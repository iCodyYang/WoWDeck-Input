"""Read queued XInput2 key edges without taking a keyboard or controller grab."""
import ctypes as C

# Xlib and XI2 stable ABI. Only the prefix up to detail/flags is needed.
class Header(C.Structure):
    _fields_ = [('type', C.c_int), ('serial', C.c_ulong), ('send', C.c_int),
                ('display', C.c_void_p), ('extension', C.c_int), ('kind', C.c_int)]


class Cookie(C.Structure):
    _fields_ = Header._fields_ + [('cookie', C.c_uint), ('data', C.c_void_p)]


class Raw(C.Structure):
    _fields_ = Header._fields_ + [('time', C.c_ulong), ('device', C.c_int),
                                  ('source', C.c_int), ('detail', C.c_int), ('flags', C.c_int)]


class Mask(C.Structure):
    _fields_ = [('device', C.c_int), ('length', C.c_int), ('bits', C.POINTER(C.c_ubyte))]


def signature(lib, name, result, *params):
    fn = getattr(lib, name)
    fn.restype, fn.argtypes = result, list(params)


class EdgeStream:
    def __init__(self, x):
        self.x = x
        self.xi = C.CDLL('libXi.so.6')
        self.opcodes = {}
        dp, ip = C.c_void_p, C.POINTER(C.c_int)
        signature(x, 'XQueryExtension', C.c_int, dp, C.c_char_p, ip, ip, ip)
        signature(x, 'XDefaultRootWindow', C.c_ulong, dp)
        signature(x, 'XFlush', C.c_int, dp)
        signature(x, 'XPending', C.c_int, dp)
        signature(x, 'XNextEvent', C.c_int, dp, dp)
        signature(x, 'XGetEventData', C.c_int, dp, C.POINTER(Cookie))
        signature(x, 'XFreeEventData', None, dp, C.POINTER(Cookie))
        signature(self.xi, 'XIQueryVersion', C.c_int, dp, ip, ip)
        signature(self.xi, 'XISelectEvents', C.c_int, dp, C.c_ulong, C.POINTER(Mask), C.c_int)

    def attach(self, handle):
        if handle in self.opcodes:
            return
        opcode, first, error = C.c_int(), C.c_int(), C.c_int()
        self.opcodes[handle] = None
        if not self.x.XQueryExtension(handle, b'XInputExtension', C.byref(opcode), C.byref(first), C.byref(error)):
            return
        major, minor = C.c_int(2), C.c_int(1)
        if self.xi.XIQueryVersion(handle, C.byref(major), C.byref(minor)) or major.value < 2:
            return
        # XIAllMasterDevices; XI_RawKeyPress=13 and XI_RawKeyRelease=14.
        bits = (C.c_ubyte * 2)(0, 0x60)
        mask = Mask(1, len(bits), bits)
        if self.xi.XISelectEvents(handle, self.x.XDefaultRootWindow(handle), C.byref(mask), 1) == 0:
            self.opcodes[handle] = opcode.value
            self.x.XFlush(handle)

    def read(self, handle, keycode):
        opcode = self.opcodes.get(handle)
        if opcode is None:
            return []
        events = []
        buffer = (C.c_long * 24)()  # sizeof(XEvent)
        cookie = C.cast(buffer, C.POINTER(Cookie))
        while self.x.XPending(handle):
            self.x.XNextEvent(handle, buffer)
            entry = cookie.contents
            if entry.type != 35 or entry.extension != opcode or entry.kind not in (13, 14):
                continue
            if not self.x.XGetEventData(handle, cookie):
                continue
            try:
                raw = C.cast(entry.data, C.POINTER(Raw)).contents
                if raw.detail == keycode and not raw.flags & (1 << 16):
                    events.append((raw.time & 0xffffffff, entry.kind == 13))
            finally:
                self.x.XFreeEventData(handle, cookie)
        return events
