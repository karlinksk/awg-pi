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

BUTTON_RE = re.compile(r"<\s*(?:ОК|OK|Да|Нет|Закрыть|Отмена)\s*>", re.IGNORECASE)

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

def main(stdscr):
    locale.setlocale(locale.LC_ALL, "")
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)
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
                    try: stdscr.addstr(y,x,s["chars"][k],curses.color_pair(1+min(6,k*7//max(1,s["len"]-1))))
                    except curses.error: pass
            s["y"]+=s["speed"]*dt
            if rng.random()<dt*8.0: s["chars"][rng.randrange(s["len"])]=rng.choice(GLYPHS)
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
        try:
            key = stdscr.get_wch()
        except curses.error:
            key = None
        navigation = {
            curses.KEY_UP: "Up", curses.KEY_DOWN: "Down",
            curses.KEY_LEFT: "Left", curses.KEY_RIGHT: "Right",
            curses.KEY_BACKSPACE: "BSpace", curses.KEY_DC: "DC",
            curses.KEY_PPAGE: "PPage", curses.KEY_NPAGE: "NPage",
            curses.KEY_HOME: "Home", curses.KEY_END: "End",
            curses.KEY_BTAB: "BTab",
        }
        if key in navigation:
            tmux("send-keys", "-t", "menu:0.0", navigation[key])
        elif key in ("\n", "\r", curses.KEY_ENTER):
            tmux("send-keys", "-t", "menu:0.0", "Enter")
        elif key in ("\x1b",):
            tmux("send-keys", "-t", "menu:0.0", "Escape")
        elif key in ("\x7f", "\b"):
            tmux("send-keys", "-t", "menu:0.0", "BSpace")
        elif key == "\t":
            tmux("send-keys", "-t", "menu:0.0", "Tab")
        elif key == "\x03":
            break
        elif isinstance(key, str) and key.isprintable():
            tmux("send-keys", "-t", "menu:0.0", "-l", key)
        time.sleep(max(0,1/20-(time.monotonic()-now)))

if __name__=="__main__":
    try:
        code = curses.wrapper(main)
    finally:
        subprocess.run(["tmux","-L",SOCKET,"kill-server"],capture_output=True)
    sys.exit(code or 0)
