"""# ASCII syrnik by JeusDEV.

Python 3.9+, no dependencies.

Run in a terminal with ANSI color support.
Works on Windows, macOS, and Linux.
Oversized models fit the window.
Ctrl+C exits cleanly.

Usage:
    python syrnik.py                      # default rotation, ASCII shading
    python syrnik.py -p -m -r             # pixel mode, interactive, reversed movement
    python syrnik.py -sc 2 -sp 90 -bg -r  # big and fast, no background, reversed rotation
    python syrnik.py -sy ".:#@" -f 60 -u  # custom ramp, 60 fps, auto rebuild

WARN: Please enable (-u | --update-build) to rebuild the model on window resize;
    useful for long sessions, costs a short rebuild pause.
    If it's lagging on window resize check this flag enabled or not.
If (-p | --pixel) is enabled, custom ramp (-sy | --symbols) has no effect.
If (-m | --manual) is enabled, (-r | --reverse) flips the arrow controls.
Manual mode (-m) requires an interactive terminal on stdin.
"""

import argparse
import math
import os
import shutil
import signal
import sys
import time
from contextlib import contextmanager
from typing import Generator, Optional

if sys.platform.startswith("win"):  # static analyzer bypass
    import ctypes
    import msvcrt
    from ctypes import wintypes
else:
    import select
    import termios
    import tty

TAU = math.tau
ESC = "\x1b["
RESET = ESC + "0m"
BG_BLACK = ESC + "40m"
RAMP = "FUCK,."
# RAMP = ".,:;irsXAhM"  # ▮

RenderResult = tuple[list[str], list[Optional[tuple[int, int, int]]]]


def clamp(x, lo=0.0, hi=1.0) -> float:
    """Clamp x to [lo, hi]."""
    return max(lo, min(hi, x))


def shak_noise(x, y, z) -> float:
    """Deterministic interpolated 3D value noise.

    Do not ask how and why. Calculated in my mind.

    "Shak." - (c) mcKisco.
    """
    ix, iy, iz = math.floor(x), math.floor(y), math.floor(z)
    u, v, w = x - ix, y - iy, z - iz
    u, v, w = u * u * (3 - 2 * u), v * v * (3 - 2 * v), w * w * (3 - 2 * w)
    def h(a, b, c):
        n = (a * 374761393 + b * 668265263 + c * 2147483647 + 719) & 0xFFFFFFFF
        n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
        return (n ^ (n >> 16)) / 4294967295.0
    def lerp(a, b, t):
        return a + (b - a) * t
    return lerp(
        lerp(lerp(h(ix, iy, iz), h(ix + 1, iy, iz), u),
             lerp(h(ix, iy + 1, iz), h(ix + 1, iy + 1, iz), u), v),
        lerp(lerp(h(ix, iy, iz + 1), h(ix + 1, iy, iz + 1), u),
             lerp(h(ix, iy + 1, iz + 1), h(ix + 1, iy + 1, iz + 1), u), v),
        w,
    )


def build_model(detail=1.0) -> list:
    """Textured in object space rounded thick disk."""
    points = []
    spacing = 0.019 / detail
    rings = []
    # Horizontal faces
    for side in (1, -1):
        count = math.ceil(0.84 / spacing)
        for k in range(count + 1):
            r = 0.84 * k / count
            rings.append((r, side * (0.325 + 0.022 * (1 - (r / 0.84) ** 2)),
                          0.052 * r, side * 1.0))
    # Vertical faces
    count = math.ceil(math.pi * 0.20 / spacing)
    for k in range(1, count):
        a = math.pi * k / count
        r, y = 0.84 + 0.16 * math.sin(a), 0.325 * math.cos(a)
        nx, ny = 0.325 * math.sin(a), 0.16 * math.cos(a)
        length = math.hypot(nx, ny)
        rings.append((r, y, nx / length, ny / length))
    # Convert rings to points in 3D space
    for r, y, nr, ny in rings:
        count = max(1, math.ceil(TAU * r / spacing))
        for k in range(count):
            a = TAU * (k + 0.31) / count
            ca, sa = math.cos(a), math.sin(a)
            # Unevenness to make a silhouette
            irregular = 1 + 0.022 * math.sin(3 * a + 0.4) + 0.014 * math.sin(7 * a - 0.8)
            x, z = r * ca * irregular, r * sa * irregular
            coarse = shak_noise(x * 5 + 11, y * 6 + 9, z * 5 + 17)
            fine = shak_noise(x * 37 + 51, y * 37 + 31, z * 37 + 29)
            bump = (fine - 0.5) * 0.018 + (coarse - 0.5) * 0.026
            px, py, pz = x + nr * ca * bump, y + ny * bump, z + nr * sa * bump
            # Colored noise on vertical faces
            face = clamp((abs(ny) - 0.40) / 0.52)
            toast = clamp((coarse - 0.30) * 2.15 + 0.12 * fine)
            toast *= face
            color = tuple(int(a0 + (a1 - a0) * toast) for a0, a1 in
                          zip((246, 208, 132), (115, 49, 15)))
            # Normal changes to catch the light
            nx, nz = nr * ca + (fine - 0.5) * 0.17, nr * sa + (coarse - 0.5) * 0.13
            length = math.sqrt(nx * nx + ny * ny + nz * nz)
            # Y-factor
            if py < 0.0:
                yf = 1.0 + py * 2.6
                if yf < 0.0:
                    yf = 0.0
                elif yf > 1.0:
                    yf = 1.0
            else:
                yf = 1.0
            # Forming list of points
            points.append((
                px, py, pz,
                nx / length, ny / length, nz / length,
                color, fine, yf
            ))
    return points


def render(points, angle, width, height, scale, symbols) -> RenderResult:
    """Perspective projection, back-face culling and a per-character z-buffer."""
    chars = [" "] * (width * height)
    colors = [None] * (width * height)
    depths = [-float("inf")] * (width * height)
    c, s = math.cos(angle), math.sin(angle)
    # Object spins around upright axis
    ce, se = 0.819152, 0.573576
    zoom = min(35.0 * scale, (width - 4) / 2.25, (height - 3) / 1.11)
    if zoom < 0.1:
        zoom = 0.1
    cx, cy = (width - 1) * 0.5, (height - 1) * 0.5
    sym_last = len(symbols) - 1
    w, h = width, height
    for x, y, z, nx, ny, nz, base, texture, y_factor in points:
        xx = c * x + s * z
        zz = -s * x + c * z
        nnx = c * nx + s * nz
        nnz = -s * nx + c * nz
        yy = ce * y - se * zz
        depth = se * y + ce * zz
        nny = ce * ny - se * nnz
        facing = se * ny + ce * nnz
        if facing <= 0.0:
            continue
        perspective = 5.0 / (5.0 - depth)
        # Col
        col = int(cx + xx * zoom * perspective + 0.5)
        if col < 0 or col >= w:
            continue
        # Row
        row = int(cy - yy * zoom * 0.49 * perspective + 0.5)
        if row < 0 or row >= h:
            continue
        idx = row * w + col
        if depth <= depths[idx]:
            continue
        depths[idx] = depth
        # Like a post processing
        d1 = -0.43 * nnx + 0.66 * nny + 0.615 * facing
        if d1 < 0.0:
            d1 = 0.0
        light = 0.6 + 0.88 * d1
        sh1 = -0.23 * nnx + 0.35 * nny + 0.908 * facing
        if sh1 > 0.0:
            shine = 0.15 * sh1 ** 16
        else:
            shine = 0.0
        s255 = 255.0 * shine
        # Final color
        br, bg, bb = base
        r = int((br * light + s255) * 0.125) * 8
        if r > 255: r = 255
        g = int((bg * light + s255) * 0.125) * 8
        if g > 255: g = 255
        b = int((bb * light + s255) * 0.125) * 8
        if b > 255: b = 255
        # Quantized truecolor keeps ANSI traffic modest without flattening shading
        if y_factor < 1.0:
            r = int(r * y_factor)
            g = int(g * y_factor)
            b = int(b * y_factor)
        colors[idx] = (r, g, b)
        # Ramp density
        density = 0.05 + 0.85 * light + 0.10 * (texture - 0.5)
        if density < 0.0:
            density = 0.0
        elif density > 1.0:
            density = 1.0
        chars[idx] = symbols[int(density * sym_last)]
    return chars, colors


def compute_detail(scale, width, height) -> float:
    """Scale detail by window area, bounded for small terminals."""
    base = min(2.2, max(1.0, scale))
    area = max(1, width) * max(1, height)
    ref = 100 * 40
    if area >= ref:
        return base
    factor = (area / ref) ** 0.5
    if factor < 0.5:
        factor = 0.5
    return base * factor


def encode_frame(chars, colors, width, height, use_pixel_mode=False, has_bg=True) -> str:
    """Serialize chars + colors into one ANSI frame string."""
    out = [ESC + "H"]
    current_color = None
    ansi_code = "48" if use_pixel_mode else "38"
    for row in range(height):
        if row:
            out.append(ESC + f"{row + 1};1H")
        for idx in range(row * width, (row + 1) * width):
            color = colors[idx]
            if use_pixel_mode:
                if color is None:
                    target_color = None if not has_bg else (0, 0, 0)
                else:
                    target_color = color
                char_to_print = " "
            else:
                target_color = color
                char_to_print = chars[idx] if color is not None else " "
            if target_color != current_color:
                if target_color is None:
                    out.append(RESET if not has_bg else RESET + BG_BLACK)
                else:
                    if not has_bg:
                        out.append(RESET)
                    out.append(ESC + f"{ansi_code};2;%d;%d;%dm" % target_color)
                current_color = target_color
            out.append(char_to_print)
    return "".join(out)


@contextmanager
def terminal(bg=True, manual=False) -> Generator[None, None, None]:
    """Restore cursor, colors, screen, and console/terminal modes on exit."""
    win = None
    unix = None
    if sys.platform.startswith("win"):
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetStdHandle.argtypes = [wintypes.DWORD]
        kernel.GetStdHandle.restype = wintypes.HANDLE
        kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        handle = kernel.GetStdHandle(-11 & 0xFFFFFFFF)
        mode = wintypes.DWORD()
        if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            raise RuntimeError("Open this script in Windows Terminal or PowerShell.")
        if not kernel.SetConsoleMode(handle, mode.value | 0x0004):
            raise RuntimeError("This terminal does not support ANSI colors.")
        win = kernel, handle, mode.value
    elif manual:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        tty.setcbreak(fd)  # keeps ISIG on, so Ctrl+C still raises SIGINT
        unix = fd, old_settings
    try:
        sys.stdout.write(ESC + "?1049h" + ESC + "?25l" + RESET + (BG_BLACK if bg else "") + ESC + "2J")
        sys.stdout.flush()
        yield
    finally:
        try:
            sys.stdout.write(RESET + ESC + "?25h" + ESC + "?1049l")
            sys.stdout.flush()
        finally:
            if win:
                win[0].SetConsoleMode(win[1], win[2])
            if unix:
                fd, old_settings = unix
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def get_arrow_direction_win() -> int:
    """Input arrows without blocking on Windows."""
    direction = 0
    while msvcrt.kbhit():
        ch = msvcrt.getch()
        if ch in (b'\xe0', b'\x00'):
            ch2 = msvcrt.getch()
            if ch2 == b'M':  # right
                direction = 1
            elif ch2 == b'K':  # left
                direction = -1
        elif ch == b'\x03':
            raise KeyboardInterrupt
    return direction


def get_arrow_direction_unix() -> int:
    """Input arrows without blocking on Unix (Linux, macOS)."""
    direction = 0
    while select.select([0], [], [], 0)[0]:
        ch = os.read(0, 1)
        if not ch:
            break
        if ch == b'\x03':
            raise KeyboardInterrupt
        if ch == b'\x1b':
            # If emulator sending with delay raise it from 0.005 to 0.02
            if not select.select([0], [], [], 0.005)[0]:
                continue
            seq = os.read(0, 2)
            if seq == b'[C':      # right
                direction = 1
            elif seq == b'[D':    # left
                direction = -1
    return direction


def positive(value) -> float:
    """Means that value cannot be 0 or less than 0."""
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a finite number greater than zero")
    return number


def main() -> None:
    """Parse args, then run the render loop until Ctrl+C.

    Rebuilds the model on window resize only with -u.
    Arrow keys drive rotation in -m mode.
    """
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-sc", "--scale", type=positive, default=1.0, help="model size multiplier (default: 1)")
    parser.add_argument("-sp", "--speed", type=positive, default=32.0, help="degrees per second (default: 32)")
    parser.add_argument("-sy", "--symbols", type=str, default=RAMP, help=f"symbols to render in ascii mode (default: \"{RAMP}\")")
    parser.add_argument("-f", "--fps", type=positive, default=30.0, help="maximum frames per second (default: 30)")
    parser.add_argument("-p", "--pixel", action="store_true", help="color background instead of symbols (default: False)")
    parser.add_argument("-bg", "--no-background", action="store_false", help="remove background (default: True)")
    parser.add_argument("-r", "--reverse", action="store_true", help="controls direction of rotation (default: False)")
    parser.add_argument("-m", "--manual", action="store_true", help="enable interactive arrow keys control mode (default: False)")
    parser.add_argument("-u", "--update-build", action="store_true", help="rebuild model on window resize (default: False)")
    args = parser.parse_args()
    if args.manual and not sys.stdin.isatty():
        parser.error("(!) -m requires an interactive terminal on stdin")
    if not sys.stdout.isatty():
        parser.error("(!) run this script directly in a terminal, without redirecting output")
    if args.reverse:
        rotation_direction = 1
    if sys.platform.startswith("win"):
        arrow_func = get_arrow_direction_win
    else:
        arrow_func = get_arrow_direction_unix
    symbols_ramp = args.symbols[::-1]
    rotation_direction = -1
    # Ctrl+C handling
    previous = signal.signal(signal.SIGTERM, signal.default_int_handler)
    # More samples for larger models, with a bounded startup/memory cost
    points = None
    current_detail = None
    current_angle = 0.0
    current_speed_pct = 0.0
    accel_smoothing = 5.0
    decel_smoothing = 12.0
    try:
        with terminal(args.no_background, args.manual):
            start = time.perf_counter()
            last_size = None
            last_frame_time = start
            buf = sys.stdout.buffer
            while True:
                frame_start = time.perf_counter()
                dt = frame_start - last_frame_time
                last_frame_time = frame_start
                size = shutil.get_terminal_size((100, 40))
                # Leave the last column unused to prevent terminal autowrap
                width, height = max(1, size.columns - 1), max(1, size.lines)
                if size != last_size:
                    buf.write((ESC + "2J").encode("ascii"))
                    last_size = size
                    # First frame always builds, then resizes only with -u
                    if points is None or args.update_build:
                        new_detail = compute_detail(args.scale, width, height)
                        if current_detail is None or abs(new_detail - current_detail) > 1e-9:
                            points = build_model(new_detail)
                            current_detail = new_detail
                if args.manual:
                    target_dir = float(arrow_func())
                    if args.reverse:
                        target_dir = -target_dir
                    # Control speed with deltaTime
                    if target_dir != 0:
                        blend = 1.0 - math.exp(-accel_smoothing * dt)
                        current_speed_pct += (target_dir - current_speed_pct) * blend
                    else:
                        blend = 1.0 - math.exp(-decel_smoothing * dt)
                        current_speed_pct += (0.0 - current_speed_pct) * blend
                    # Rotate object with calculated bias
                    speed_rad = math.radians(args.speed) * current_speed_pct
                    current_angle = (current_angle + speed_rad * dt) % TAU
                    angle = current_angle
                else:
                    # Standard automatic rotation. Negative yaw moves object clockwise
                    angle = rotation_direction * math.radians(args.speed) * (frame_start - start) % TAU
                chars, colors = render(points, angle, width, height, args.scale, symbols_ramp)
                # Magic
                buf.write(encode_frame(
                    chars, colors, width, height,
                    args.pixel, args.no_background
                ).encode("utf-8"))
                buf.flush()
                delay = 1.0 / args.fps - (time.perf_counter() - frame_start)
                if delay > 0:
                    time.sleep(delay)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    main()
