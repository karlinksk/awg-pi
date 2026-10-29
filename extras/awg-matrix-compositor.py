#!/usr/bin/env python3
"""EXPERIMENTAL read-through terminal compositor for existing AWG dialog.
Independent tmux pane holds the unmodified menu. No gateway changes.
"""
import curses
import locale
import os
import random
import re
import subprocess
import sys
import time

GLYPHS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ@#$%&+-*/"
SGR = re.compile(r"\x1b\[([0-9;]*)m")
ESC = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\([A-Za-z0-9]")
SOCKET = "awg-matrix-render-%s-%s" % (os.getuid(), os.getpid())
PALETTE = [(190,255,190),(90,255,90),(0,255,0),(0,200,0),(0,140,0),(0,85,0),(0,42,0)]

BUTTON_RE = re.compile(r"<\s*(?:ОК|OK|Да|Нет|Yes|No|Закрыть|Close|Отмена|Cancel)\s*>", re.IGNORECASE)

def shadow_row_columns(row):
    """Identify the bottom drop-shadow: long *blank* white-on-black runs.

    Dialog's selected item uses white-on-black bold characters as well,
    but has text on that row. Its bottom shadow consists entirely of spaces.
    Never classify a blank drop-shadow as a highlighted menu item.
    """
    run = []
    shadow = set()
    for x, cell in enumerate([*row, None]):
        if cell is not None and cell[0] == " " and cell[1:] == (7, 0, True):
            run.append(x)
        else:
            if len(run) >= 24:
                shadow.update(run)
            run = []
    return shadow


def overlay_role(ch, fg, bg, bold, button_row):
    """Separate dialog surface, selection, button and ncurses shadow."""
    if bg == 6:  # old cyan screen behind the dialog
        return "topline" if ch != " " else None
    if bg == 0 and fg == 0:  # dark drop-shadow is not selected content
        return None
    if bg == 0 and bold and fg in (3, 7):
        return "button" if button_row else "selection"
    if bg == 4:  # opaque window/menu: use Matrix canvas near-black
        return "panel"
    return "normal"


def tmux(*args, capture=False):
    p = subprocess.run(["tmux","-L",SOCKET,*args], capture_output=True)
    if p.returncode and not capture:
        raise RuntimeError(p.stderr.decode(errors="replace"))
    return p.stdout.decode("utf-8", errors="replace")

def parse_line(line, cols):
    # DIALOG screen is transparent by default; only its occupied cells overlay Matrix.
    out = [None] * cols
    fg, bg, bold = 7, -1, False
    x = 0
    index = 0
    while index < len(line) and x < cols:
        match = SGR.match(line,index)
        if match:
            vals=[int(v) if v else 0 for v in match.group(1).split(";")]
            for v in vals:
                if v == 0: fg,bg,bold=7,-1,False
                elif v == 1: bold=True
                elif v == 22: bold=False
                elif 30 <= v <= 37: fg=v-30
                elif 40 <= v <= 47: bg=v-40
                elif v == 39: fg=7
                elif v == 49: bg=-1
            index=match.end()
            continue
        match=ESC.match(line,index)
        if match:
            index=match.end()
            continue
        char=line[index]
        index += 1
        if char in "\r\n": continue
        # Background-color blocks identify the actual dialog surface.
        if bg >= 0 or char not in " ":
            out[x]=(char,fg,bg,bold)
        x+=1
    return out


# The Matrix renderer refreshes at 20 fps, but clipboard input must NOT be
# throttled to one keystroke per redraw. A config paste can contain thousands
# of characters. Drain ncurses' ready input and forward consecutive printable
# characters through one literal tmux call (not a subprocess per character).
# Flush before control keys to preserve their order and native dialog behavior.

# Native mouse escape bytes are unsafe to inject into the inner tmux dialog:
# on some terminals ESC inside the sequence closes the widget. Instead, map a
# click to ordinary dialog keyboard actions, using ONLY the currently visible,
# validated tmux snapshot. A row click selects; only an explicit button click
# can submit. Unsupported widgets and out-of-surface clicks do nothing.
ANY_BUTTON_RE = re.compile(r"<[^<>]{1,28}>")

def menu_keys_for_click(screen, x, y):
    """Return safe keyboard steps for the visible item/button, else ()."""
    if not screen or y < 0 or y >= len(screen) or x < 0 or x >= len(screen[y]):
        return ()
    row = screen[y]
    line = "".join(cell[0] if cell is not None else " " for cell in row)

    buttons = list(BUTTON_RE.finditer(line))
    if buttons and y >= len(screen) // 2:
        # An unrecognized button makes Tab order ambiguous: do not guess.
        if len(buttons) != len(list(ANY_BUTTON_RE.finditer(line))):
            return ()
        for index, match in enumerate(buttons):
            if match.start() <= x < match.end():
                active = [
                    idx for idx, button in enumerate(buttons)
                    if any(
                        cell is not None and cell[2] == 0 and cell[3]
                        and cell[1] in (3, 7)
                        for cell in row[button.start():button.end()]
                    )
                ]
                # A solitary <OK>/<Close> token in textbox prose is NOT
                # necessarily a dialog button. Require real active styling.
                if len(active) != 1:
                    return ()
                steps = (index - active[0]) % len(buttons)
                return ("Tab",) * steps + ("Enter",)
        return ()

    # Only a real menu/list with exactly one highlighted item can be targeted.
    # Selected item tag=yellow-on-black, label=white-on-black. This excludes
    # prose, the animated background, text inputs and dialog buttons.
    selected = []
    for sy, cells in enumerate(screen):
        caption = "".join(cell[0] if cell is not None else " " for cell in cells)
        if BUTTON_RE.search(caption):
            continue
        tag_x = [i for i, c in enumerate(cells)
                 if c and c[0].isalnum() and c[1] == 3
                 and c[2] == 0 and c[3]]
        label_x = [i for i, c in enumerate(cells)
                   if c and c[0].isalpha() and c[1] == 7
                   and c[2] == 0 and c[3]]
        if tag_x and label_x and min(tag_x) < min(label_x):
            selected.append((sy, min(tag_x), min(label_x)))
    if len(selected) != 1:
        return ()
    sy, tag_col, label_col = selected[0]
    if abs(y - sy) > 40:
        return ()
    # Every intervening row must have a tag and label in the SAME columns.
    # This stops a click below the list or on a different dialog widget from
    # causing an unintended long run of arrow presses.
    for cy in range(min(y, sy), max(y, sy) + 1):
        cells = screen[cy]
        if max(tag_col, label_col) >= len(cells):
            return ()
        tag, label = cells[tag_col], cells[label_col]
        if (not tag or not label or not tag[0].isalnum()
                or not label[0].isalpha() or tag[2] not in (0, 4)
                or label[2] not in (0, 4)):
            return ()
    # Click the text/tag itself, not blank padding, borders or rain.
    target = screen[y][x]
    if x < tag_col or not target or not target[0].isalnum():
        return ()
    if target[2] not in (0, 4):
        return ()
    delta = y - sy
    return (("Down",) * delta if delta > 0 else ("Up",) * -delta)


def forward_verified_click(x, y, screen, state):
    """Reject stale screenshots before sending any click-derived key."""
    if screen is None:
        return
    if not screen or y < 0 or y >= len(screen):
        return
    width = len(screen[y])
    if not 0 <= x < width:
        return
    raw = tmux("capture-pane", "-e", "-p", "-t", "menu:0.0", capture=True)
    if not raw:
        return
    fresh = [parse_line(line, width) for line in raw.splitlines()[:len(screen)]]
    if fresh != screen:
        return
    keys = menu_keys_for_click(screen, x, y)
    if not keys:
        return
    # A client may report RELEASED and CLICKED for the same press. Do not
    # submit a button twice, especially across a dialog transition.
    if keys[-1] == "Enter":
        stamp = state.get("button_click")
        now = time.monotonic()
        if stamp and stamp[:2] == (x, y) and now - stamp[2] < 0.4:
            return
        state["button_click"] = (x, y, now)
    tmux("send-keys", "-t", "menu:0.0", *keys)


def forward_pending_input(stdscr, captured=None, mouse_state=None):
    navigation = {
        curses.KEY_UP: "Up", curses.KEY_DOWN: "Down",
        curses.KEY_LEFT: "Left", curses.KEY_RIGHT: "Right",
        curses.KEY_BACKSPACE: "BSpace", curses.KEY_DC: "DC",
        curses.KEY_PPAGE: "PPage", curses.KEY_NPAGE: "NPage",
        curses.KEY_HOME: "Home", curses.KEY_END: "End",
        curses.KEY_BTAB: "BTab",
    }
    literal = []
    if mouse_state is None:
        mouse_state = {}

    def flush_literal():
        if literal:
            # -- keeps pasted text starting with "-" out of tmux option parsing.
            tmux("send-keys", "-t", "menu:0.0", "-l", "--", "".join(literal))
            literal.clear()

    # Cap work per frame so rain and window resizing remain responsive during
    # enormous pastes; the remaining PTY input stays queued for the next frame.
    for _ in range(8192):
        try:
            key = stdscr.get_wch()
        except curses.error:
            break
        if key == curses.KEY_MOUSE:
            # Xterm-style terminals report wheel notches as mouse buttons 4/5.
            # Handle one arrow per wheel event instead of relying on the
            # terminal's multi-arrow scrolling fallback.
            flush_literal()
            try:
                _, mx, my, _, buttons = curses.getmouse()
            except curses.error:
                continue
            if buttons & curses.BUTTON4_PRESSED:
                tmux("send-keys", "-t", "menu:0.0", "Up")
            elif buttons & curses.BUTTON5_PRESSED:
                tmux("send-keys", "-t", "menu:0.0", "Down")
            elif buttons & curses.BUTTON1_PRESSED:
                mouse_state["down"] = (mx, my)
            elif buttons & curses.BUTTON1_RELEASED:
                down = mouse_state.pop("down", None)
                if down == (mx, my):
                    forward_verified_click(mx, my, captured, mouse_state)
            elif buttons & curses.BUTTON1_CLICKED:
                mouse_state.pop("down", None)
                forward_verified_click(mx, my, captured, mouse_state)
        elif key in navigation:
            flush_literal()
            tmux("send-keys", "-t", "menu:0.0", navigation[key])
        elif key in ("\n", "\r", curses.KEY_ENTER):
            flush_literal()
            tmux("send-keys", "-t", "menu:0.0", "Enter")
        elif key == "\x1b":
            flush_literal()
            tmux("send-keys", "-t", "menu:0.0", "Escape")
        elif key in ("\x7f", "\b"):
            flush_literal()
            tmux("send-keys", "-t", "menu:0.0", "BSpace")
        elif key == "\t":
            flush_literal()
            tmux("send-keys", "-t", "menu:0.0", "Tab")
        elif key == "\x03":
            flush_literal()
            return True
        elif isinstance(key, str) and key.isprintable():
            literal.append(key)
            if len(literal) >= 2048:
                flush_literal()
    flush_literal()
    return False

def main(stdscr):
    locale.setlocale(locale.LC_ALL, "")
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)
    # Request native wheel events from SSH terminals that support xterm mouse
    # tracking. Without it, a wheel notch may be emulated as several arrow
    # keys and skip multiple menu entries. No tracking is enabled in classic UI.
    try:
        curses.mousemask(curses.BUTTON4_PRESSED | curses.BUTTON5_PRESSED |
                         curses.BUTTON1_PRESSED | curses.BUTTON1_RELEASED |
                         curses.BUTTON1_CLICKED)
        curses.mouseinterval(0)
    except curses.error:
        pass
    curses.start_color()
    curses.use_default_colors()
    for i,c in enumerate(PALETTE):
        if curses.can_change_color() and curses.COLORS > 16:
            # 7 mutable colors outside base terminal palette
            curses.init_color(16+i,*[int(v*1000/255) for v in c])
            curses.init_pair(i+1,16+i,-1)
        else:
            curses.init_pair(i+1,curses.COLOR_GREEN,-1)
    for i in range(8):
        for j in range(8):
            curses.init_pair(10+i*8+j,i,j)
    # Use exactly the same green for selected-row fill and the OK-button glyphs.
    # The selected row uses black letters for contrast.
    bright_green = 46 if curses.COLORS >= 256 else curses.COLOR_GREEN
    curses.init_pair(90, curses.COLOR_BLACK, bright_green)
    curses.init_pair(91, bright_green, curses.COLOR_BLACK)
    curses.init_pair(92, curses.COLOR_CYAN, curses.COLOR_BLACK)
    for fg in range(8):
        curses.init_pair(100 + fg, fg, curses.COLOR_BLACK)
    h,w=stdscr.getmaxyx()
    if h<22 or w<70:
        raise RuntimeError("Терминал должен быть не меньше 70x22")
    # Mark only the inner tmux menu, never the SSH-side menu process.
    # Exit 42 from this pane tells the SSH-side launcher to switch to classic.
    tmux("-f","/dev/null","new-session","-d","-x",str(w),"-y",str(h),"-s","menu",
         "sudo /usr/bin/env AWG_MENU_MATRIX_INNER=1 /usr/local/sbin/awg-menu --classic")
    tmux("set-option", "-g", "remain-on-exit", "on")
    rng=random.Random()
    streams=[]
    dims=None
    last=time.monotonic()
    last_snapshot=0
    captured=[]
    mouse_state={}
    while True:
        h,w=stdscr.getmaxyx()
        if (h,w)!=dims:
            if h<22 or w<70: break
            tmux("resize-window","-t","menu:0","-x",str(w),"-y",str(h))
            streams=[{"y":rng.uniform(-h,h),"speed":rng.uniform(3,7),"len":rng.randrange(9,17),
                      "chars":[rng.choice(GLYPHS) for _ in range(17)]}
                     for _ in range(0,w,2)]
            dims=h,w
        now=time.monotonic()
        dt=min(.12,now-last)
        last=now
        if now-last_snapshot>=0.10:
            status=tmux("display-message","-p","-t","menu:0.0",
                        "#{pane_dead} #{pane_dead_status}",capture=True).strip()
            if status.startswith("1 "):
                try: return int(status.split()[1])
                except (IndexError, ValueError): return 0
            raw=tmux("capture-pane","-e","-p","-t","menu:0.0",capture=True)
            if not raw: break
            captured=[parse_line(line,w) for line in raw.splitlines()[:h]]
            last_snapshot=now
        stdscr.erase()
        for i,s in enumerate(streams):
            x=i*2
            for k in range(s["len"]):
                y=int(s["y"])-k
                if 0<=y<h:
                    # Each visible glyph flickers independently as it falls.
                    # Only its character changes, never the stream geometry.
                    if rng.random()<min(1.0,dt*6.0):
                        s["chars"][k]=rng.choice(GLYPHS)
                    try: stdscr.addstr(y,x,s["chars"][k],curses.color_pair(1+min(6,k*7//max(1,s["len"]-1))))
                    except curses.error: pass
            s["y"]+=s["speed"]*dt
            if s["y"]-s["len"]>h: s["y"]=rng.uniform(-h,0)
        for y,row in enumerate(captured):
            # Dialog button row contains < ОК > etc. Color *all* button glyphs alike.
            label = "".join(cell[0] if cell is not None else " " for cell in row)
            button_row = bool(BUTTON_RE.search(label))
            shadow = shadow_row_columns(row)
            highlight = [x for x, cell in enumerate(row) if cell is not None and
                         x not in shadow and cell[2] == 0 and cell[3] and
                         cell[1] in (3, 7) and cell[0] != " "]
            highlighted_cells = set()
            if highlight and not button_row:
                first, last = min(highlight), max(highlight)
                highlighted_cells.update(range(max(0, first-1), min(w, last+3)))
            for x,cell in enumerate(row):
                if cell is None or x in shadow:
                    continue
                ch,fg,bg,bold=cell
                if bg < 0:
                    if ch == " ":
                        continue
                    bg = 0
                role = overlay_role(ch, fg, bg, bold, button_row)
                if x in highlighted_cells and role not in (None, "topline"):
                    role = "selection"
                if role is None:
                    continue
                if role == "selection":
                    attr = curses.color_pair(90)
                elif role == "button":
                    attr = curses.color_pair(91) | curses.A_BOLD
                elif role == "topline":
                    attr = curses.color_pair(92)
                elif role == "panel":
                    attr = curses.color_pair(100+fg)
                    if bold: attr |= curses.A_BOLD
                else:
                    attr = curses.color_pair(10+fg*8+bg)
                    if bold: attr |= curses.A_BOLD
                try:
                    stdscr.addstr(y,x,ch,attr)
                except curses.error:
                    pass
        stdscr.refresh()
        if forward_pending_input(stdscr, captured, mouse_state):
            break
        time.sleep(max(0,1/20-(time.monotonic()-now)))

def run_with_mouse_cleanup(stdscr):
    try:
        return main(stdscr)
    finally:
        # Stop terminal-side mouse reporting before curses restores the TTY.
        try:
            curses.mousemask(0)
        except curses.error:
            pass


if __name__=="__main__":
    try:
        code = curses.wrapper(run_with_mouse_cleanup)
    finally:
        subprocess.run(["tmux","-L",SOCKET,"kill-server"],capture_output=True)
    sys.exit(code or 0)
