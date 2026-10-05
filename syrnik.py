"""ASCII syrnik. Python 3.9+, no dependencies.

Run in a terminal with ANSI color support.
Oversized models fit the window.
Ctrl+C exits cleanly.
"""

import argparse
import math
import os
import shutil
import signal
import sys
import time
from contextlib import contextmanager

if os.name == "nt":
    import msvcrt

TAU = math.tau
ESC = "\x1b["
RAMP = "FUCK,."
# RAMP = ".,:;irsXAhM"  # ▮

def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def grain(x, y, z):
    """Deterministic, smoothly interpolated 3D value noise."""
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
             lerp(h(ix, iy + 1, iz + 1), h(ix + 1, iy + 1, iz + 1), u), v), w)


def build_model(detail=1.0):
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
            coarse = grain(x * 5 + 11, y * 6 + 9, z * 5 + 17)
            fine = grain(x * 37 + 51, y * 37 + 31, z * 37 + 29)
            bump = (fine - 0.5) * 0.018 + (coarse - 0.5) * 0.026
            px, py, pz = x + nr * ca * bump, y + ny * bump, z + nr * sa * bump
            # Colored noise on vertical faces
            face = clamp((abs(ny) - 0.40) / 0.52)
            toast = clamp((coarse - 0.30) * 2.15 + 0.12 * fine)
            toast *= face
            color = tuple(int(a0 + (a1 - a0) * toast) for a0, a1 in
                          zip((246, 208, 132), (115, 49, 15)))
            # Additional small colored grain
            # if fine < 0.28:
            #     color = tuple(int(c * 0.73) for c in color)
            # if fine > 0.76:
            #     color = tuple(int(c * 0.7 + v * 0.3) for c, v in zip(color, (255, 233, 174)))
            # Normal changes to catch the light
            nx, nz = nr * ca + (fine - 0.5) * 0.17, nr * sa + (coarse - 0.5) * 0.13
            length = math.sqrt(nx * nx + ny * ny + nz * nz)
            points.append((px, py, pz, nx / length, ny / length, nz / length,
                           color, fine))
    return points


def render(points, angle, width, height, scale, symbols):
    """Perspective projection, back-face culling and a per-character z-buffer."""
    chars = [" "] * (width * height)
    colors = [None] * (width * height)
    depths = [-float("inf")] * (width * height)
    c, s = math.cos(angle), math.sin(angle)
    # Object spins around upright axis
    ce, se = 0.819152, 0.573576
    zoom = min(35.0 * scale, (width - 4) / 2.25, (height - 3) / 1.11)
    zoom = max(0.1, zoom)
    cx, cy = (width - 1) / 2, (height - 1) / 2
    for x, y, z, nx, ny, nz, base, texture in points:
        xx, zz = c * x + s * z, -s * x + c * z
        nnx, nnz = c * nx + s * nz, -s * nx + c * nz
        yy, depth = ce * y - se * zz, se * y + ce * zz
        nny, facing = ce * ny - se * nnz, se * ny + ce * nnz
        if facing <= 0:
            continue
        perspective = 5.0 / (5.0 - depth)
        col = int(cx + xx * zoom * perspective + 0.5)
        row = int(cy - yy * zoom * 0.49 * perspective + 0.5)
        if col < 0 or col >= width or row < 0 or row >= height:
            continue
        idx = row * width + col
        if depth <= depths[idx]:
            continue
        depths[idx] = depth
        # Like a post processing
        diffuse = max(0.0, -0.43 * nnx + 0.66 * nny + 0.615 * facing)
        light = 0.6 + 0.88 * diffuse  # 0.32 0.68
        shine = 0.15 * max(0.0, -0.23 * nnx + 0.35 * nny + 0.908 * facing) ** 16
        final_color = tuple(min(255, int((v * light + 255 * shine) / 8) * 8) for v in base)
        # Quantized truecolor keeps ANSI traffic modest without flattening shading
        if y < 0:
            factor = clamp(1.0 + (y * 2.6), 0.0, 1.0)
            colors[idx] = tuple(int(c * factor) for c in final_color)
        else:
            colors[idx] = final_color
        # Ramp density
        density = clamp(0.05 + 0.85 * light + 0.10 * (texture - 0.5))
        chars[idx] = symbols[int(density * (len(symbols) - 1))]
    return chars, colors


def encode_frame(chars, colors, width, height, use_pixel_mode=False, has_bg=True):
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
                    out.append(ESC + "0m" if not has_bg else ESC + "0m" + ESC + "40m")
                else:
                    if not has_bg:
                        out.append(ESC + "0m")
                    out.append(ESC + f"{ansi_code};2;%d;%d;%dm" % target_color)
                current_color = target_color
            out.append(char_to_print)
    return "".join(out)


@contextmanager
def terminal(bg=True):
    """Restore the cursor, colors, screen and Windows console mode on exit."""
    win = None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
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
    try:
        sys.stdout.write(ESC + "?1049h" + ESC + "?25l" + ESC + "0m" + ((ESC + "40m") if bg else "") + ESC + "2J")
        sys.stdout.flush()
        yield
    finally:
        try:
            sys.stdout.write(ESC + "0m" + ESC + "?25h" + ESC + "?1049l")
            sys.stdout.flush()
        finally:
            if win:
                win[0].SetConsoleMode(win[1], win[2])


def get_arrow_direction_win():
    """Input arrows without blocking Windows Console."""
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


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a finite number greater than zero")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-sc", "--scale", type=positive, default=1.0, help="model size multiplier (default: 1)")
    parser.add_argument("-sp", "--speed", type=positive, default=32.0, help="degrees per second (default: 32)")
    parser.add_argument("-sy", "--symbols", type=str, default=RAMP, help=f"symbols to render in ascii mode (default: {RAMP})")
    parser.add_argument("-f", "--fps", type=positive, default=30.0, help="maximum frames per second (default: 30)")
    parser.add_argument("-p", "--pixel", action="store_true", help="color background instead of symbols (default: False)")
    parser.add_argument("-bg", "--no-background", action="store_false", help="sets a black background (default: True)")
    parser.add_argument("-r", "--reverse", action="store_true", help="controls direction of rotation (default: False)")
    parser.add_argument("-m", "--manual", action="store_true", help="enable interactive arrow keys control mode (default: False)")
    args = parser.parse_args()
    if not sys.stdout.isatty():
        parser.error("(!) run this script directly in a terminal, without redirecting output")
    rotation_direction = -1
    if args.reverse:
        rotation_direction = 1
    symbols_ramp = args.symbols[::-1]
    # More samples for larger models, with a bounded startup/memory cost.
    points = build_model(min(2.2, max(1.0, args.scale)))
    def stop(_signum, _frame):
        raise KeyboardInterrupt
    previous = signal.signal(signal.SIGTERM, stop)
    current_angle = 0.0
    current_speed_pct = 0.0
    accel_smoothing = 5.0
    decel_smoothing = 12.0
    try:
        with terminal(args.no_background):
            start = time.perf_counter()
            last_size = None
            last_frame_time = start
            while True:
                frame_start = time.perf_counter()
                dt = frame_start - last_frame_time
                last_frame_time = frame_start
                size = shutil.get_terminal_size((100, 40))
                # Leave the last column unused to prevent terminal autowrap.
                width, height = max(1, size.columns - 1), max(1, size.lines)
                if size != last_size:
                    sys.stdout.write(ESC + "2J")
                    last_size = size
                if args.manual:
                    target_dir = 0.0
                    if os.name == "nt":
                        target_dir = float(get_arrow_direction_win())
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
                sys.stdout.write(encode_frame(
                    chars, colors, width, height,
                    args.pixel, args.no_background
                ))
                sys.stdout.flush()
                delay = 1.0 / args.fps - (time.perf_counter() - frame_start)
                if delay > 0:
                    time.sleep(delay)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    main()
