from gint import *
import time
import math

# =============================================================================
# CONSTANTS & CONFIG
# =============================================================================

SCREEN_W = 320
SCREEN_H = 528

# Layout Dimensions
KBD_H = 260
TAB_H = 30
PICK_HEADER_H = 40
PICK_FOOTER_H = 45
PICK_ITEM_H = 50

# =============================================================================
# THEMES
# =============================================================================

def safe_rgb(r, g, b):
    return C_RGB(r, g, b)

THEMES = {
    'light': {
        'modal_bg': C_WHITE,
        'kbd_bg':   C_WHITE,
        'key_bg':   C_WHITE,
        'key_spec': safe_rgb(28, 29, 28), # Secondary (Light Grey)
        'key_out':  C_DARK,               # Dark (Unused for key borders now)
        'txt':      safe_rgb(4, 4, 4),
        'txt_dim':  safe_rgb(8, 8, 8),
        'accent':   safe_rgb(1, 11, 26),
        'txt_acc':  C_WHITE,
        'hl':       safe_rgb(28, 29, 28), # Highlight matches secondary
        'check':    C_WHITE
    },
    'dark': {
        'modal_bg': safe_rgb(7, 7, 8),
        'kbd_bg':   safe_rgb(7, 7, 8),
        'key_bg':   safe_rgb(7, 7, 8),
        'key_spec': safe_rgb(11, 11, 12), # Secondary (Dark Grey)
        'key_out':  safe_rgb(12, 19, 31),
        'txt':      C_WHITE,
        'txt_dim':  safe_rgb(8, 8, 8),
        'accent':   safe_rgb(12, 19, 31),
        'txt_acc':  C_WHITE,
        'hl':       safe_rgb(11, 11, 12),
        'check':    C_WHITE
    },
    'grey': {
        'modal_bg': C_LIGHT,
        'kbd_bg':   C_LIGHT,
        'key_bg':   C_WHITE,
        'key_spec': 0xCE59,
        'key_out':  C_BLACK,
        'txt':      C_BLACK,
        'txt_dim':  safe_rgb(8, 8, 8),
        'accent':   C_BLACK,
        'txt_acc':  C_WHITE,
        'hl':       0xCE59,
        'check':    C_WHITE
    }
}

def get_theme(name_or_dict) -> dict:
    if isinstance(name_or_dict, dict): return name_or_dict
    return THEMES.get(name_or_dict, THEMES['light'])

# =============================================================================
# REUSABLE LIST VIEW
# =============================================================================

class ListView:
    def __init__(self, rect, items, row_h=40, theme='light', headers_h=None):
        """
        rect: (x, y, w, h) tuple
        items: List of dicts {'text': str, 'type': 'item'|'section', 'height': int, ...} OR list of strings
        """
        self.x, self.y, self.w, self.h = rect
        # Normalize items
        self.items = []
        for it in items:
            if isinstance(it, dict): self.items.append(it)
            else: self.items.append({'text': str(it), 'type': 'item'})

        self.base_row_h = row_h
        self.headers_h = headers_h if headers_h else row_h
        self.theme = get_theme(theme)

        # Layout State
        self.total_h = 0
        self.recalc_layout()

        # Selection & Scroll
        self.selected_index = -1
        self.scroll_y = 0
        self.max_scroll = max(0, self.total_h - self.h)

        # Select first selectable item
        self.select_next(0, 1)

        # Touch State
        self.is_dragging = False
        self.touch_start_y = 0
        self.touch_start_idx = 0
        self.touch_start_time = 0
        self.touch_acc_y = 0.0 # Accumulator for drag distance
        self.touch_initial_item_idx = -1
        self.long_press_triggered = False

        # Configuration
        self.drag_threshold = 10
        self.long_press_delay = 0.5 # seconds
        self.snap_sensitivity = 1.0 # 1.0 = 1 item height drag moves 1 item

    def recalc_layout(self):
        """Calculate positions and heights of all items."""
        total_h = 0
        for it in self.items:
            h = it.get('height', self.headers_h if it.get('type') == 'section' else self.base_row_h)
            it['_h'] = h
            it['_y'] = total_h
            total_h += h
        self.total_h = total_h
        self.max_scroll = max(0, self.total_h - self.h)

    def select_next(self, start_idx, step):
        """Find next selectable item"""
        idx = start_idx
        count = len(self.items)
        if count == 0:
            self.selected_index = -1
            return

        # Safety loop limit
        for _ in range(count):
            if 0 <= idx < count:
                if self.items[idx].get('type', 'item') != 'section':
                    self.selected_index = idx
                    self.ensure_visible()
                    return
            idx += step
            # Clamp logic
            if idx < 0 or idx >= count: break

    def ensure_visible(self):
        """Scroll to keep selected_index in view"""
        if self.selected_index < 0 or self.selected_index >= len(self.items): return

        it = self.items[self.selected_index]
        item_top = it['_y']
        item_bot = item_top + it['_h']

        view_top = self.scroll_y
        view_bot = self.scroll_y + self.h

        if item_top < view_top:
            self.scroll_y = item_top
        elif item_bot > view_bot:
            self.scroll_y = item_bot - self.h

        self.clamp_scroll()

    def clamp_scroll(self):
        self.max_scroll = max(0, self.total_h - self.h)
        self.scroll_y = max(0, min(self.max_scroll, self.scroll_y))

    def update(self, events):
        """
        Process events.
        """
        now = time.monotonic()

        # Touch Handling
        touch_up = None
        touch_down = None
        current_touch = None

        # Pre-process touch events
        for e in events:
            if e.type == KEYEV_TOUCH_DOWN:
                touch_down = e
                current_touch = e
            elif e.type == KEYEV_TOUCH_UP:
                touch_up = e
            elif e.type == KEYEV_TOUCH_DRAG: # Some envs might emit this
                current_touch = e

        # Also look for simulated drag via repeatedly polled DOWN events if native drag not available
        if not current_touch and touch_down:
            current_touch = touch_down

        # 1. Start Touch
        if touch_down and not self.is_dragging and self.touch_start_time == 0:
            if self.x <= touch_down.x < self.x + self.w and self.y <= touch_down.y < self.y + self.h:
                self.touch_start_y = touch_down.y
                self.touch_start_time = now

                # Determine which item was touched initially
                local_y = touch_down.y - self.y + self.scroll_y
                self.touch_initial_item_idx = self.get_index_at(local_y)

                # Anchor drag to the item under finger if valid, else selection
                if self.touch_initial_item_idx != -1:
                    self.touch_start_idx = self.touch_initial_item_idx
                    # Immediate visual feedback
                    if 0 <= self.touch_initial_item_idx < len(self.items):
                        if self.items[self.touch_initial_item_idx].get('type') != 'section':
                            self.selected_index = self.touch_initial_item_idx
                            self.ensure_visible()
                else:
                    self.touch_start_idx = self.selected_index

                self.is_dragging = False
                self.long_press_triggered = False
                self.touch_acc_y = 0.0

        # Long Press Detection (Time-based)
        if self.touch_start_time != 0 and not self.is_dragging and not self.long_press_triggered:
            if now - self.touch_start_time > 0.8: # 800ms threshold
                self.long_press_triggered = True
                # Return 'long' action immediately
                idx = self.selected_index
                if 0 <= idx < len(self.items):
                    return ('long', idx, self.items[idx])

        # ... Or use the last known touch if we are already in a touch sequence
        # We need a way to know "current finger position" even if no new event came this frame,
        # but typically we get continuous events. If we don't, we can't drag.

        # 2. Touch Move / Drag
        if self.touch_start_time != 0:
             # Find the most recent position event
             last_pos = current_touch if current_touch else touch_down

             if last_pos:
                dy = last_pos.y - self.touch_start_y

                # Check for drag threshold
                # User req: "If the drag is more than one item height, then apply scrolling"
                if not self.is_dragging:
                    if abs(dy) > self.base_row_h: # Threshold is one item height
                        self.is_dragging = True
                        self.long_press_triggered = True

                if self.is_dragging:
                    # Scroll Logic (Snap)
                    # Dragging UP (negative dy) -> Move down in list

                    # More advanced "Pixel-based" mapping to index
                    # We map the total pixel offset (start_y + scroll_y_offset - dy) to an index
                    # This allows variable row heights natural feeling

                    # 1. Calculate theoretical pixel position
                    # We want to move the "originally selected item" by -dy pixels relative to the view center?
                    # Or simpler: The "selection cursor" moves by -dy pixels.

                    # Current selection top in pixels
                    if 0 <= self.touch_start_idx < len(self.items):
                        start_item_y = self.items[self.touch_start_idx]['_y']

                        # Target Y for the selection top
                        target_y = start_item_y - dy

                        # Find index at target_y
                        # Wescan items to find which one contains target_y
                        # But to fix the "clamping" issue with sections:
                        # If the index found is a section, or we are crossing a section...

                        found_idx = -1
                        for i, it in enumerate(self.items):
                            if it['_y'] <= target_y < it['_y'] + it['_h']:
                                found_idx = i
                                break

                        if found_idx == -1:
                           if target_y < 0: found_idx = 0
                           else: found_idx = len(self.items) - 1

                        # Apply Clamping Logic:
                        # If found_idx is a SECTION, we check where in the section we are.
                        # User wants: "consider the selection to enter the next section first item
                        # only when the scroll amount is above the title height."

                        # Implementation interpretation:
                        # If we land on a section header (found_idx is Section),
                        # we should STAY on the *previous* item unless we are past the section header?
                        # Or STAY on the section header (But sections aren't selectable...)?
                        # "Selectable" logic usually skips sections.

                        # Refined logic: Drag maps to a pixel Y. That pixel Y lands on an item.
                        # If it lands on a Section:
                        #   If we came from above (moving down), we need to drag PAST the section entirely to select the item below it.
                        #   If we came from below (moving up), we need to drag ABOVE the section entirely to select item above.

                        # Effectively, the "active area" for the section header does not trigger selection change until passed?
                        # Let's try: if match is section, map to previous valid item if (target_y < section_center) else next valid item?
                        # User said: "only when the scroll amount is above the title height"

                        if self.items[found_idx].get('type') == 'section':
                             # We are hovering over a section
                             # Check overlap
                             sec_y = self.items[found_idx]['_y']
                             sec_h = self.items[found_idx]['_h']
                             overlap = target_y - sec_y

                             # If we are dragging DOWN (dy < 0, target_y increasing), we are moving to next section
                             if dy < 0:
                                 # We are moving down the list.
                                 # Only jump to next item if we are really deep into the section or past it?
                                 # Actually, if we are conceptually "dragging the paper", moving finger UP (negative dy)
                                 # means we want to see lower items.
                                 pass

                             # Logic:
                             # If we land on section, look at adjacent items.
                             # If we are closer to the top of section, pick item above.
                             # If we are closer to bottom, pick item below.
                             # "Glitch: separator ... flicker between the two voices"

                             # Let's enforce a "dead zone" corresponding to the section height.
                             # If target_y falls within a section's vertical space, keep the selection
                             # on the *previously selected item* (from start of drag or previous frame)
                             # UNLESS we have crossed it?

                             # Simpler: Don't select the section. Select the adjacent valid item based on direction,
                             # BUT require the "target_y" to be fully into the valid item's space.

                             # If target_y is in section -> Don't change selection from what it would be if we were at the edge?

                             if self.selected_index < found_idx:
                                  # We were above, moving down.
                                  # Stay above until we are purely past the section?
                                  # effectively, for the section to be skipped, target_y must be >= sec_y + sec_h
                                  # But found_idx says we are < sec_y + sec_h.
                                  # So stay at found_idx - 1 (or whatever was valid above)
                                  final_idx = found_idx - 1
                             else:
                                  # We were below, moving up.
                                  # Stay below until target_y < sec_y
                                  final_idx = found_idx + 1

                             # Boundary checks
                             final_idx = max(0, min(len(self.items)-1, final_idx))

                        else:
                             final_idx = found_idx

                        if 0 <= final_idx < len(self.items) and self.items[final_idx].get('type') != 'section':
                            self.selected_index = final_idx
                            self.ensure_visible()

        # 3. Touch Release
        if touch_up:
            if self.touch_start_time != 0:
                # Valid release sequence
                ret = None

                if not self.is_dragging and not self.long_press_triggered:
                    # Click Candidate
                    local_y = touch_up.y - self.y + self.scroll_y
                    release_idx = self.get_index_at(local_y)

                    # Logic: If release is on same item as start, it's a click.
                    if release_idx == self.touch_initial_item_idx and release_idx >= 0:
                         if self.items[release_idx].get('type') != 'section':
                             # Ensure selection updates to the clicked item
                             self.selected_index = release_idx
                             self.ensure_visible()
                             ret = ('click', release_idx, self.items[release_idx])

                # Reset
                self.touch_start_time = 0
                self.is_dragging = False
                return ret

            # If touch_up happened but we weren't tracking, ignore it (stray event)

        # 4. Long Press
        if self.touch_start_time != 0 and not self.is_dragging and not self.long_press_triggered:
            if now - self.touch_start_time > self.long_press_delay:
                self.long_press_triggered = True
                # Trigger on current selection or initial?
                # Usually initial item
                if 0 <= self.touch_initial_item_idx < len(self.items):
                     it = self.items[self.touch_initial_item_idx]
                     if it.get('type') != 'section':
                         self.selected_index = self.touch_initial_item_idx
                         return ('long', self.touch_initial_item_idx, it)

        # 5. Keys
        for e in events:
            if e.type == KEYEV_DOWN or (e.type == KEYEV_HOLD and e.key in [KEY_UP, KEY_DOWN]):
                if e.key == KEY_UP:
                    self.select_next(self.selected_index - 1, -1)
                elif e.key == KEY_DOWN:
                    self.select_next(self.selected_index + 1, 1)
                elif e.key == KEY_EXE:
                    if self.selected_index >= 0:
                        return ('click', self.selected_index, self.items[self.selected_index])

        return None

    def get_index_at(self, y):
        # Linear scan is sufficient for likely list sizes (<500)
        # Binary search could be used since _y is sorted
        for i, it in enumerate(self.items):
            if it['_y'] <= y < it['_y'] + it['_h']:
                return i
        return -1

    def draw_item(self, x, y, item, is_selected):
        # Can be overridden by subclass or assigned
        t = self.theme
        h = item['_h']

        if item.get('type') == 'section':
            drect(x, y, x + self.w, y + h, t['key_spec'])
            drect_border(x, y, x + self.w, y + h, C_NONE, 1, t['key_spec'])
            dtext_opt(x + 10, y + h//2, t['txt_dim'], C_NONE, DTEXT_LEFT, DTEXT_MIDDLE, str(item['text']), -1)
        else:
            bg = t['hl'] if is_selected else t['modal_bg']
            drect(x, y, x + self.w, y + h, bg)
            drect_border(x, y, x + self.w, y + h, C_NONE, 1, t['key_spec'])

            x_off = 20
            if item.get('checked'):
                self.draw_check(x + 10, y + (h-20)//2, t)
                x_off = 40

            dtext_opt(x + x_off, y + h//2, t['txt'], C_NONE, DTEXT_LEFT, DTEXT_MIDDLE, str(item['text']), -1)

            # Draw Arrow if requested
            if item.get('arrow'):
                 ar_x = x + self.w - 15
                 ar_y = y + h//2
                 c = t['txt_dim']
                 dline(ar_x - 4, ar_y - 4, ar_x, ar_y, c)
                 dline(ar_x - 4, ar_y + 4, ar_x, ar_y, c)

    def draw(self):
        t = self.theme
        drect(self.x, self.y, self.x + self.w, self.y + self.h, t['modal_bg'])

        # Lazy Rendering: Find start index
        start_y = self.scroll_y
        end_y = self.scroll_y + self.h

        # Simple scan to find start (optimize later if needed)
        start_idx = 0
        for i, it in enumerate(self.items):
            if it['_y'] + it['_h'] > start_y:
                start_idx = i
                break

        # Draw visible items
        for i in range(start_idx, len(self.items)):
            it = self.items[i]
            if it['_y'] >= end_y: break # Stop if below view

            item_y = self.y + it['_y'] - self.scroll_y
            self.draw_item(self.x, item_y, it, (i == self.selected_index))

        # Scrollbar
        if self.max_scroll > 0:
            sb_w = 4
            ratio = self.h / (self.total_h if self.total_h > 0 else 1)
            thumb_h = max(20, int(self.h * ratio))

            scroll_ratio = self.scroll_y / self.max_scroll
            thumb_y = self.y + int(scroll_ratio * (self.h - thumb_h))

            sb_x = self.x + self.w - sb_w - 2
            drect(sb_x, thumb_y, sb_x + sb_w, thumb_y + thumb_h, t['accent'])

    def draw_check(self, x, y, t):
        drect(x, y, x+20, y+20, t['accent'])
        c = t['check']
        dline(x+4, y+10, x+8, y+14, c)
        dline(x+8, y+14, x+15, y+5, c)

# =============================================================================
# KEYBOARD WIDGET
# =============================================================================

LAYOUTS = {
    'qwerty': [list("1234567890"), list("qwertyuiop"), list("asdfghjkl:"), list("zxcvbnm,._")],
    'azerty': [list("1234567890"), list("azertyuiop"), list("qsdfghjklm"), list("wxcvbn,._:")],
    'qwertz': [list("1234567890"), list("qwertzuiop"), list("asdfghjkl:"), list("yxcvbnm,._")],
    'abc':    [list("1234567890"), list("abcdefghij"), list("klmnopqrst"), list("uvwxyz,._:")]
}

LAYOUT_SYM = [
    list("1234567890"),
    list("@#$_&-+()/"),
    list("=\\<*\"':;!?"),
    list("{}[]^~`|<>")
]

class Keyboard:
    def __init__(self, default_tab=0, enable_tabs=True, numpad_opts=None, theme='light', layout='qwerty'):
        self.y = SCREEN_H - KBD_H
        self.visible = True
        self.current_tab = default_tab
        self.enable_tabs = enable_tabs
        self.shift = False
        self.tabs = ["ABC", "Sym", "Math"]
        self.last_key = None
        self.numpad_opts = numpad_opts if numpad_opts else {'float': True, 'neg': True}

        self.theme: dict = get_theme(theme)
        self.layout_alpha = LAYOUTS.get(layout, LAYOUTS['qwerty'])
        if layout != 'qwerty':
            self.tabs[0] = layout.upper() if len(layout) <= 3 else "Txt"

    def draw_key(self, x, y, w, h, label, is_special=False, is_pressed=False, is_accent=False):
        t = self.theme
        # Background
        if is_pressed: bg = t['hl']
        elif is_accent: bg = t['accent']
        elif is_special: bg = t['key_spec']
        else: bg = t['key_bg']

        txt_col = t['txt_acc'] if is_accent else t['txt']
        # Soft Border using secondary color
        border_col = t['key_spec']

        drect(x + 1, y + 1, x + w - 1, y + h - 1, bg)
        drect_border(x, y, x + w, y + h, C_NONE, 1, border_col)
        dtext_opt(x + w//2, y + h//2, txt_col, C_NONE, DTEXT_CENTER, DTEXT_MIDDLE, label, -1)

    def draw_tabs(self):
        t = self.theme
        tab_w = SCREEN_W // 3
        border_col = t['key_spec']
        for i, tab_name in enumerate(self.tabs):
            tx = i * tab_w
            is_active = (i == self.current_tab)
            bg = t['kbd_bg'] if is_active else t['key_spec']
            drect(tx, self.y, tx + tab_w, self.y + TAB_H, bg)
            drect_border(tx, self.y, tx + tab_w, self.y + TAB_H, C_NONE, 1, border_col)
            if is_active:
                drect(tx + 1, self.y + TAB_H - 1, tx + tab_w - 1, self.y + TAB_H + 1, t['kbd_bg'])
            dtext_opt(tx + tab_w//2, self.y + TAB_H//2, t['txt'], C_NONE, DTEXT_CENTER, DTEXT_MIDDLE, tab_name, -1)

    def draw_grid(self):
        layout = LAYOUT_SYM if self.current_tab == 1 else self.layout_alpha
        grid_y = self.y + TAB_H
        row_h = 45
        for r, row in enumerate(layout):
            count = len(row)
            kw = SCREEN_W // count
            for c, char in enumerate(row):
                kx = c * kw
                ky = grid_y + r * row_h
                label = char.upper() if (self.current_tab == 0 and self.shift) else char
                is_pressed = (self.last_key == label)
                self.draw_key(kx, ky, kw, row_h, label, False, is_pressed)

        # Bottom Control Row
        bot_y = grid_y + 4 * row_h
        bot_h = row_h
        self.draw_key(0, bot_y, 50, bot_h, "CAPS", True, self.shift, False)
        self.draw_key(50, bot_y, 50, bot_h, "<-", True, self.last_key == "BACKSPACE", False)
        self.draw_key(100, bot_y, 160, bot_h, "Space", False, self.last_key == " ", False)
        self.draw_key(260, bot_y, 60, bot_h, "EXE", False, self.last_key == "ENTER", True)

    def update_grid(self, x, y, type):
        grid_y = self.y + TAB_H
        row_h = 45
        row_idx = (y - grid_y) // row_h
        if 0 <= row_idx < 4:
            layout = LAYOUT_SYM if self.current_tab == 1 else self.layout_alpha
            if row_idx >= len(layout): return None
            row_chars = layout[row_idx]
            kw = SCREEN_W // len(row_chars)
            col_idx = min(len(row_chars)-1, max(0, x // kw))
            char = row_chars[col_idx]
            if self.current_tab == 0 and self.shift: char = char.upper()
            if type == KEYEV_TOUCH_DOWN: self.last_key = char
            return char
        elif row_idx == 4:
            cmd = None
            if x < 50:
                if type == KEYEV_TOUCH_DOWN: self.shift = not self.shift
            elif x < 100: cmd = "BACKSPACE"
            elif x < 260: cmd = " "
            else: cmd = "ENTER"
            if type == KEYEV_TOUCH_DOWN: self.last_key = cmd
            return cmd
        return None

    def get_math_rects(self):
        keys = []
        start_y = self.y + TAB_H
        total_h = KBD_H - TAB_H
        row_h = total_h // 4
        side_w = 50
        center_w = SCREEN_W - (side_w * 2)
        numpad_w = center_w // 3
        for i, char in enumerate(["+", "-", "*", "/"]):
            keys.append((0, start_y + i*row_h, side_w, row_h, char, False, True, False))
        r_chars = [("%", False, True, False), (" ", False, True, False), ("<-", "BACKSPACE", True, False), ("EXE", "ENTER", False, True)]
        for i, (disp, val, spec, acc) in enumerate(r_chars):
            keys.append((SCREEN_W - side_w, start_y + i*row_h, side_w, row_h, disp, val, spec, acc))
        nums = [["1","2","3"], ["4","5","6"], ["7","8","9"]]
        for r in range(3):
            for c in range(3):
                keys.append((side_w + c*numpad_w, start_y + r*row_h, numpad_w, row_h, nums[r][c], False, False, False))
        y_bot = start_y + 3*row_h
        unit_w = center_w // 6
        bot_row = [",", "#", "0", "=", "."]
        widths  = [1, 1, 2, 1, 1]
        cur_x = side_w
        for i, char in enumerate(bot_row):
            w = widths[i] * unit_w
            if i == len(bot_row) - 1: w = (side_w + center_w) - cur_x
            keys.append((cur_x, y_bot, w, row_h, char, False, False, False))
            cur_x += w
        return keys

    def get_numpad_rects(self):
        keys = []
        start_y = self.y
        total_h = KBD_H
        row_h = total_h // 4
        action_w = 80
        digit_w = (SCREEN_W - action_w) // 3
        keys.append((SCREEN_W - action_w, start_y, action_w, row_h, "<-", "BACKSPACE", True, False))
        keys.append((SCREEN_W - action_w, start_y + row_h, action_w, row_h*3, "EXE", "ENTER", False, True))
        nums = [["1","2","3"], ["4","5","6"], ["7","8","9"]]
        for r in range(3):
            for c in range(3):
                keys.append((c*digit_w, start_y + r*row_h, digit_w, row_h, nums[r][c], False, False, False))
        y_bot = start_y + 3*row_h
        bot_keys = []
        if self.numpad_opts['neg']: bot_keys.append("-")
        bot_keys.append("0")
        if self.numpad_opts['float']: bot_keys.append(".")
        if len(bot_keys) > 0:
            bw = (SCREEN_W - action_w) // len(bot_keys)
            cur_x = 0
            for i, k in enumerate(bot_keys):
                w = bw
                if i == len(bot_keys) - 1: w = (SCREEN_W - action_w) - cur_x
                keys.append((cur_x, y_bot, w, row_h, k, False, False, False))
                cur_x += w
        return keys

    def draw_keys_from_rects(self, rects):
        for x, y, w, h, label, val, is_spec, is_acc in rects:
            check_val = val if val is not False else label
            is_pressed = (self.last_key == check_val)
            self.draw_key(x, y, w, h, label, is_spec, is_pressed, is_acc)

    def update_keys_from_rects(self, rects, x, y, type):
        for rx, ry, rw, rh, label, val, is_spec, is_acc in rects:
            if rx <= x < rx + rw and ry <= y < ry + rh:
                ret = val if val is not False else label
                if type == KEYEV_TOUCH_DOWN: self.last_key = ret
                return ret
        return None

    def draw(self):
        if not self.visible: return
        t = self.theme
        drect(0, self.y, SCREEN_W, SCREEN_H, t['kbd_bg'])
        dhline(self.y, t['key_spec'])
        if self.enable_tabs:
            self.draw_tabs()
            if self.current_tab == 2:
                self.draw_keys_from_rects(self.get_math_rects())
            else:
                self.draw_grid()
        else:
            self.draw_keys_from_rects(self.get_numpad_rects())

    def update(self, ev):
        # We only set visual feedback on TOUCH DOWN
        if ev.type == KEYEV_TOUCH_DOWN:
            self.last_key = None # Clear previous visual press

        if not self.visible: return None

        x, y = ev.x, ev.y
        if y < self.y: return None

        # Only process taps on tabs, ignore drags
        if self.enable_tabs and y < self.y + TAB_H:
            if ev.type == KEYEV_TOUCH_DOWN:
                tab_w = SCREEN_W // 3
                self.current_tab = min(2, max(0, x // tab_w))
            return None

        # Determine active update method
        method = None
        if not self.enable_tabs: method = lambda t: self.update_keys_from_rects(self.get_numpad_rects(), x, y, t)
        elif self.current_tab == 2: method = lambda t: self.update_keys_from_rects(self.get_math_rects(), x, y, t)
        else: method = lambda t: self.update_grid(x, y, t)

        return method(ev.type)

# =============================================================================
# LIST PICKER WIDGET
# =============================================================================

class ListPicker:
    def __init__(self, options, prompt="Select:", theme="light", multi=False, touch_mode=KEYEV_TOUCH_DOWN):
        self.options = options
        self.prompt = prompt
        self.theme_name = theme if isinstance(theme, str) else 'light'
        self.theme: dict = get_theme(theme)
        self.multi = multi
        self.touch_mode = touch_mode
        self.selected_indices = set() if multi else {0}

        self.header_h = PICK_HEADER_H
        self.footer_h = PICK_FOOTER_H
        self.view_h = SCREEN_H - self.header_h - self.footer_h
        self.btn_w = 60
        self.last_action = None

        # Initialize ListView
        # Convert options to dicts if needed, or ListView handles strings
        # We need to inject 'checked' state for multi-select
        self.lv_items = []
        for i, opt in enumerate(options):
            it = {'text': str(opt), 'type': 'item', 'idx': i}
            if multi and i in self.selected_indices: it['checked'] = True
            self.lv_items.append(it)

        rect = (0, self.header_h, SCREEN_W, self.view_h)
        self.list_view = ListView(rect, self.lv_items, row_h=PICK_ITEM_H, theme=self.theme_name)
        if not multi and len(self.lv_items) > 0:
            self.list_view.selected_index = 0

    def draw_nav_btn(self, x, w, h, type, is_pressed):
        t = self.theme
        bg = t['hl'] if is_pressed else t['key_spec']
        y = SCREEN_H - h

        drect(x, y, x + w, SCREEN_H, bg)
        drect_border(x, y, x + w, SCREEN_H, C_NONE, 1, t['key_spec'])

        cx, cy = x + w//2, y + h//2
        col = t['txt']

        if type == "UP":
            dpoly([cx, cy-5, cx-5, cy+5, cx+5, cy+5], col, C_NONE)
        elif type == "DOWN":
            dpoly([cx, cy+5, cx-5, cy-5, cx+5, cy-5], col, C_NONE)

    def draw_close_icon(self, x, y, sz, col):
        dline(x, y, x+sz, y+sz, col)
        dline(x, y+sz, x+sz, y, col)
        dline(x+1, y, x+sz+1, y+sz, col)
        dline(x+1, y+sz, x+sz+1, y, col)

    def draw(self):
        t = self.theme
        dclear(t['modal_bg'])

        # ListView (Draw first so Header/Footer cover any spill)
        # Sync multi-select checkmarks
        if self.multi:
            for it in self.list_view.items:
                it['checked'] = (it['idx'] in self.selected_indices)

        self.list_view.draw()

        # Header
        drect(0, 0, SCREEN_W, self.header_h, t['accent'])
        dtext_opt(SCREEN_W//2, self.header_h//2, t['txt_acc'], C_NONE, DTEXT_CENTER, DTEXT_MIDDLE, self.prompt, -1)
        self.draw_close_icon(15, 15, 10, t['txt_acc'])

        # Footer
        fy = SCREEN_H - self.footer_h
        drect(0, fy, SCREEN_W, SCREEN_H, t['key_spec'])
        dhline(fy, t['key_spec'])

        self.draw_nav_btn(0, self.btn_w, self.footer_h, "UP", self.last_action == "PAGE_UP")
        self.draw_nav_btn(SCREEN_W - self.btn_w, self.btn_w, self.footer_h, "DOWN", self.last_action == "PAGE_DOWN")

        ok_pressed = (self.last_action == "OK")
        ok_bg = t['hl'] if ok_pressed else t['key_spec']
        ok_rect_x = self.btn_w
        ok_rect_w = SCREEN_W - 2 * self.btn_w
        drect(ok_rect_x, fy, ok_rect_x + ok_rect_w, SCREEN_H, ok_bg)
        drect_border(ok_rect_x, fy, ok_rect_x + ok_rect_w, SCREEN_H, C_NONE, 1, t['key_spec'])

        label = "OK" if self.multi else "Select"
        dtext_opt(SCREEN_W//2, fy + self.footer_h//2, t['txt'], C_NONE, DTEXT_CENTER, DTEXT_MIDDLE, label, -1)

    def run(self):
        # Clear any lingering events
        clearevents()
        cleareventflips()

        touch_latched = False

        while True:
            self.draw()
            dupdate()
            cleareventflips()

            ev = pollevent()
            events = []
            while ev.type != KEYEV_NONE:
                events.append(ev)
                ev = pollevent()

            if keypressed(KEY_EXIT) or keypressed(KEY_DEL):
                return None

            # --- Footer / Nav Keys ---
            key_pg_up = keypressed(KEY_LEFT)
            key_pg_dn = keypressed(KEY_RIGHT)

            # Pass events to ListView first
            # We filter out touches that are in header/footer to prevent ListView from acting on them
            lv_events = []
            footer_touch = None
            header_touch = None

            for e in events:
                if e.type in [KEYEV_TOUCH_DOWN, KEYEV_TOUCH_UP, KEYEV_TOUCH_DRAG]:
                    if e.y < self.header_h:
                        if e.type == KEYEV_TOUCH_DOWN: header_touch = e # Capture down for header
                        elif e.type == KEYEV_TOUCH_UP: header_touch = e
                    elif e.y >= SCREEN_H - self.footer_h:
                         if e.type == KEYEV_TOUCH_DOWN: footer_touch = e
                         elif e.type == KEYEV_TOUCH_UP: footer_touch = e
                    else:
                        lv_events.append(e) # Pass to list view
                else:
                    lv_events.append(e) # Pass keys

            action = self.list_view.update(lv_events)

            if action:
                type, idx, item = action
                if type == 'click':
                    if self.multi:
                        real_idx = item['idx']
                        if real_idx in self.selected_indices: self.selected_indices.remove(real_idx)
                        else: self.selected_indices.add(real_idx)
                    else:
                        return self.options[item['idx']]

            if key_pg_up:
                self.list_view.scroll_y = max(0, self.list_view.scroll_y - self.list_view.h)
                self.list_view.clamp_scroll()
            if key_pg_dn:
                self.list_view.scroll_y = min(self.list_view.max_scroll, self.list_view.scroll_y + self.list_view.h)
                self.list_view.clamp_scroll()

            # Handle Footer/Header Touches
            # Check Latch for DOWN mode
            ignore_action = (self.touch_mode == KEYEV_TOUCH_DOWN and touch_latched)

            # Header
            if header_touch and header_touch.type == self.touch_mode:
                 if not ignore_action and header_touch.x < 40:
                     clearevents()
                     cleareventflips()
                     return None

            # Footer
            if footer_touch:
                 if footer_touch.type == self.touch_mode and not ignore_action:
                     if footer_touch.x < self.btn_w: self.last_action = "PAGE_UP"
                     elif footer_touch.x > SCREEN_W - self.btn_w: self.last_action = "PAGE_DOWN"
                     else: self.last_action = "OK"

                     if self.touch_mode == KEYEV_TOUCH_DOWN: touch_latched = True

            # Reset latch on any UP
            for e in events:
                if e.type == KEYEV_TOUCH_UP: touch_latched = False

            if self.last_action:
                 if self.last_action == "PAGE_UP":
                     self.list_view.scroll_y = max(0, self.list_view.scroll_y - self.list_view.h)
                     self.list_view.clamp_scroll()
                 elif self.last_action == "PAGE_DOWN":
                     self.list_view.scroll_y = min(self.list_view.max_scroll, self.list_view.scroll_y + self.list_view.h)
                     self.list_view.clamp_scroll()
                 elif self.last_action == "OK":
                     clearevents()
                     cleareventflips()
                     if self.multi: return [self.options[i] for i in sorted(self.selected_indices)]
                     else:
                         if self.list_view.selected_index >= 0:
                            return self.options[self.list_view.items[self.list_view.selected_index]['idx']]
                 self.last_action = None

            time.sleep(0.01)

            # Enforce scroll bounds after any input
            # if self.cursor_idx < self.page_start: self.page_start = self.cursor_idx
            # elif self.cursor_idx >= self.page_start + self.items_per_page: self.page_start = self.cursor_idx - self.items_per_page + 1

            # Small sleep to prevent busy loop eating battery/CPU
            time.sleep(0.01)


# =============================================================================
# PUBLIC FUNCTIONS
# =============================================================================


def input(prompt="Input:", type="alpha_numeric", theme="light", layout="qwerty", touch_mode=KEYEV_TOUCH_DOWN):
    # Re-implementing input function since it seems missing or was overwritten
    t = get_theme(theme)
    clearevents()
    cleareventflips()

    # Kbd config
    start_tab = 0
    enable_tabs = True
    numpad_opts = None

    if type.startswith("numeric_"):
        enable_tabs = False
        allow_float = "int" not in type
        allow_neg = "negative" in type
        numpad_opts = {'float': allow_float, 'neg': allow_neg}
    elif type == "math": start_tab = 2

    kbd = Keyboard(default_tab=start_tab, enable_tabs=enable_tabs, numpad_opts=numpad_opts, theme=theme, layout=layout)
    text = ""
    running = True
    touch_latched = False

    while running:
        dclear(t['modal_bg'])

        # Header
        drect(0, 0, SCREEN_W, PICK_HEADER_H, t['accent'])
        dtext_opt(SCREEN_W//2, PICK_HEADER_H//2, t['txt_acc'], C_NONE, DTEXT_CENTER, DTEXT_MIDDLE, prompt, -1)

        # Close Button
        dline(15, 15, 25, 25, t['txt_acc'])
        dline(25, 15, 15, 25, t['txt_acc'])
        dline(16, 15, 26, 25, t['txt_acc'])
        dline(26, 15, 16, 25, t['txt_acc'])

        # Input Box
        box_y = 60; box_h = 40
        drect_border(10, box_y, SCREEN_W - 10, box_y + box_h, t['hl'], 2, t['txt'])
        dtext(15, box_y + 10, t['txt'], text + "_")

        kbd.draw()
        dupdate()
        cleareventflips()

        ev = pollevent()
        events = []
        while ev.type != KEYEV_NONE:
            events.append(ev)
            ev = pollevent()

        # Physical Keys
        if keypressed(KEY_EXIT): return None
        if keypressed(KEY_EXE): return text
        if keypressed(KEY_DEL) and len(text) > 0: text = text[:-1]

        # Touch & Virtual Kbd
        for e in events:
            # Latch Reset
            if e.type == KEYEV_TOUCH_UP:
                touch_latched = False
                kbd.last_key = None

            # Close Button (Respect touch_mode)
            should_close = (e.type == touch_mode)
            if touch_mode == KEYEV_TOUCH_DOWN and touch_latched: should_close = False

            if should_close and e.y < PICK_HEADER_H and e.x < 40:
                clearevents()
                cleareventflips()
                return None

            # Keyboard (Touch Down Only)
            if e.type == KEYEV_TOUCH_DOWN and not touch_latched:
                # Don't type if touching close button area
                if e.y < PICK_HEADER_H and e.x < 40:
                    pass
                else:
                    touch_latched = True
                    res = kbd.update(e)
                    if res:
                        if res == "ENTER":
                            clearevents()
                            cleareventflips()
                            return text
                        elif res == "BACKSPACE": text = text[:-1]
                        elif len(res) == 1: text += res

        time.sleep(0.01)
    return text


def pick(options, prompt="Select:", theme="light", multi=False, touch_mode=KEYEV_TOUCH_DOWN):
    picker = ListPicker(options, prompt, theme, multi, touch_mode=touch_mode)
    return picker.run()

class ConfirmationDialog:
    def __init__(self, title, body, ok_text="OK", cancel_text="Cancel", theme="light", touch_mode=KEYEV_TOUCH_DOWN):
        self.title = title
        self.body = body
        self.ok_text = ok_text
        self.cancel_text = cancel_text
        self.theme = get_theme(theme)
        self.touch_mode = touch_mode
        self.header_h = 40
        self.footer_h = 45
        self.btn_w = SCREEN_W // 2

    def draw_btn(self, x, y, w, h, text, pressed):
        t = self.theme
        bg = t['hl'] if pressed else t['key_spec']
        drect(x, y, x + w, y + h, bg)
        drect_border(x, y, x + w, y + h, C_NONE, 1, t['key_spec'])
        dtext_opt(x + w//2, y + h//2, t['txt'], C_NONE, DTEXT_CENTER, DTEXT_MIDDLE, text, -1)

    def draw(self, btn_ok_pressed, btn_cn_pressed):
        t = self.theme
        dclear(t['modal_bg'])

        # Header
        drect(0, 0, SCREEN_W, self.header_h, t['accent'])
        dtext_opt(SCREEN_W//2, self.header_h//2, t['txt_acc'], C_NONE, DTEXT_CENTER, DTEXT_MIDDLE, self.title, -1)

        # Body
        cy = (SCREEN_H - self.header_h - self.footer_h) // 2 + self.header_h
        dtext_opt(SCREEN_W//2, cy, t['txt'], C_NONE, DTEXT_CENTER, DTEXT_MIDDLE, self.body, -1)

        # Footer
        fy = SCREEN_H - self.footer_h
        self.draw_btn(0, fy, self.btn_w, self.footer_h, self.cancel_text, btn_cn_pressed)
        self.draw_btn(self.btn_w, fy, self.btn_w, self.footer_h, self.ok_text, btn_ok_pressed)

    def run(self):
        clearevents()
        cleareventflips()

        touch_latched = False
        btn_ok_pressed = False
        btn_cn_pressed = False

        while True:
            self.draw(btn_ok_pressed, btn_cn_pressed)
            dupdate()
            cleareventflips()

            # Key Handling
            if keypressed(KEY_EXIT) or keypressed(KEY_DEL): return False
            if keypressed(KEY_EXE): return True

            # Event Handling
            ev = pollevent()
            events = []
            while ev.type != KEYEV_NONE:
                events.append(ev)
                ev = pollevent()

            touch = None
            for e in events:
                if e.type == KEYEV_TOUCH_DOWN and not touch_latched:
                    touch_latched = True
                    touch = e
                elif e.type == KEYEV_TOUCH_UP:
                    touch_latched = False
                    touch = e

            if touch:
                tx, ty = touch.x, touch.y
                fy = SCREEN_H - self.footer_h

                is_cancel = (ty >= fy and tx < self.btn_w)
                is_ok = (ty >= fy and tx >= self.btn_w)

                if touch.type == KEYEV_TOUCH_DOWN:
                    if is_cancel: btn_cn_pressed = True
                    elif is_ok: btn_ok_pressed = True

                if touch.type == self.touch_mode:
                    if is_cancel:
                        clearevents()
                        cleareventflips()
                        return False
                    elif is_ok:
                        clearevents()
                        cleareventflips()
                        return True

                if touch.type == KEYEV_TOUCH_UP:
                    btn_cn_pressed = False
                    btn_ok_pressed = False

            time.sleep(0.01)

def ask(title, body, ok_text="OK", cancel_text="Cancel", theme="light", touch_mode=KEYEV_TOUCH_DOWN):
    dlg = ConfirmationDialog(title, body, ok_text, cancel_text, theme, touch_mode=touch_mode)
    return dlg.run()