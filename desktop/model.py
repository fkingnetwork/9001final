"""UI-independent conversion, document editing, statistics and export."""
from collections import Counter
import csv

from PIL import Image, ImageDraw
from backend.color_science import rgb_to_lab, delta_e_2000
from backend.image_processing import Parameters, Cell, COLORS, convert_image


class Document:
    def __init__(self):
        self.pattern = []
        self.undo_stack = []
        self.redo_stack = []

    def replace(self, pattern):
        self.pattern = pattern
        self.undo_stack.clear()
        self.redo_stack.clear()

    def edit(self, x, y, code):
        old = self.pattern[y][x]
        if old.code == code:
            return
        difference = delta_e_2000(rgb_to_lab(old.original), COLORS[code]['lab']) if code else 0
        new = Cell(code, old.original, difference)
        self.pattern[y][x] = new
        self.undo_stack.append((x, y, old, new))
        self.undo_stack = self.undo_stack[-200:]
        self.redo_stack.clear()

    def history(self, redo=False):
        source = self.redo_stack if redo else self.undo_stack
        target = self.undo_stack if redo else self.redo_stack
        if source:
            x, y, old, new = entry = source.pop()
            self.pattern[y][x] = new if redo else old
            target.append(entry)

    def statistics(self):
        cells = [c for row in self.pattern for c in row]
        beads = [c for c in cells if c.code]
        return (Counter(c.code for c in beads), len(cells) - len(beads),
                sum(c.difference for c in beads) / max(1, len(beads)),
                max((c.difference for c in beads), default=0))

    def export(self, path, kind):
        if not self.pattern:
            raise ValueError('Generate a pattern first.')
        if kind in ('list', 'matrix'):
            with open(path, 'w', newline='', encoding='utf-8-sig') as output:
                writer = csv.writer(output)
                if kind == 'matrix':
                    writer.writerows([c.code or '' for c in row] for row in self.pattern)
                else:
                    writer.writerow(['code', 'name', 'quantity'])
                    for code, count in self.statistics()[0].most_common():
                        writer.writerow([code, COLORS[code]['name'], count])
            return
        size = 44 if kind == 'codes' else 24
        image = Image.new('RGB', (len(self.pattern[0]) * size, len(self.pattern) * size), 'white')
        draw = ImageDraw.Draw(image)
        for y, row in enumerate(self.pattern):
            for x, cell in enumerate(row):
                box = (x * size, y * size, (x + 1) * size - 1, (y + 1) * size - 1)
                color = COLORS[cell.code] if cell.code else None
                draw.rectangle(box, fill=color['displayHex'] if color else '#e5e7eb',
                               outline='#aaaaaa' if kind != 'plain' else None)
                if kind == 'codes' and color:
                    ink = 'white' if sum(color['rgb'].values()) < 360 else '#202020'
                    draw.text(((x + .5) * size, (y + .5) * size), cell.code,
                              fill=ink, anchor='mm', font_size=13)
        image.save(path, format='PNG')
