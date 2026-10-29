"""Deterministic, redistributable material fixtures; no portrait-specific layout."""
from dataclasses import dataclass
import numpy as np
from PIL import Image, ImageDraw


@dataclass
class Fixture:
    name: str
    profile: str
    image: Image.Image
    description: str


def materials():
    items = []
    logo = Image.new('RGBA', (256, 256), 'white')
    d = ImageDraw.Draw(logo)
    d.rounded_rectangle((28, 28, 228, 228), radius=34, fill='#244c91')
    d.ellipse((61, 61, 119, 119), fill='white')
    d.ellipse((146, 146, 193, 193), fill='white')
    d.rectangle((119, 112, 136, 143), fill='#d83b35')
    items.append(Fixture('logo-holes-accent', 'cartoon', logo, 'Flat logo, two holes and a rare red accent'))
    letters = Image.new('RGBA', (256, 256), 'white')
    d = ImageDraw.Draw(letters)
    # Deliberately sub-cell width at 16; strokes traverse cells vertically.
    for box in ((52, 40, 55, 215), (92, 40, 95, 215), (53, 124, 94, 127)):
        d.rectangle(box, fill='black')
    d.ellipse((135, 65, 217, 189), outline='black', width=5)
    items.append(Fixture('lettering-thin-strokes', 'lineart', letters, 'Thin H and O; continuity and an enclosed counter'))
    fox = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(fox)
    d.polygon([(40, 38), (102, 70), (151, 70), (217, 36), (204, 172), (128, 225), (52, 170)], fill='#ce6b28')
    d.polygon([(55, 62), (94, 84), (60, 111)], fill='#242526')
    d.polygon([(200, 61), (162, 84), (196, 111)], fill='#242526')
    d.polygon([(58, 139), (105, 144), (128, 199), (151, 144), (198, 139), (128, 219)], fill='#f2f0e8')
    d.ellipse((83, 120, 96, 131), fill='#242526')
    d.ellipse((160, 120, 173, 131), fill='#242526')
    d.polygon([(113, 178), (144, 178), (128, 193)], fill='#242526')
    items.append(Fixture('cartoon-fox', 'cartoon', fox, 'Transparent cartoon, eyes, ears and angular outline'))
    animal = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(animal)
    d.ellipse((55, 95, 195, 193), fill='#744326')
    d.ellipse((161, 63, 215, 127), fill='#744326')
    d.polygon([(168, 77), (162, 33), (182, 67)], fill='#744326')
    d.polygon([(192, 72), (213, 35), (210, 91)], fill='#744326')
    d.line((75, 168, 66, 224), fill='#744326', width=9)
    d.line((174, 171, 188, 224), fill='#744326', width=9)
    d.arc((9, 67, 90, 159), 40, 294, fill='#744326', width=6)
    d.ellipse((196, 86, 201, 91), fill='white')
    items.append(Fixture('animal-silhouette', 'cartoon', animal, 'Animal silhouette, thin legs, tail and small eye'))
    y, x = np.mgrid[:256, :256]
    rng = np.random.default_rng(1701)
    fruit = np.empty((256, 256, 4), dtype=np.uint8)
    fruit[..., :3] = np.clip(222 + y[..., None]*.055 + np.zeros((256, 256, 3)), 0, 255)
    fruit[..., 3] = 255
    shape = ((x-128)/82)**2 + ((y-135)/87)**2 < 1
    shade = np.clip(.5 + .5*(1-((x-97)**2+(y-99)**2)/22000), .32, 1)
    texture = rng.normal(0, 2.8, (256, 256))
    values = np.stack((218*shade+texture, 51*shade+texture, 31*shade+texture), axis=-1)
    fruit[shape, :3] = np.clip(values[shape], 0, 255).astype(np.uint8)
    image = Image.fromarray(fruit)
    d = ImageDraw.Draw(image)
    d.line((128, 59, 136, 35), fill='#744326', width=7)
    d.ellipse((131, 34, 174, 53), fill='#307346')
    items.append(Fixture('shaded-object', 'photo', image, 'Procedural shaded fruit with texture, not a real photograph'))
    scene = np.zeros((256, 256, 4), dtype=np.uint8)
    scene[..., 0] = 75+y*.42
    scene[..., 1] = 140+y*.18
    scene[..., 2] = 210-y*.2
    scene[..., 3] = 255
    image = Image.fromarray(scene)
    d = ImageDraw.Draw(image)
    d.ellipse((180, 29, 216, 65), fill='#f5d755')
    d.polygon([(0, 169), (75, 67), (144, 174)], fill='#66758a')
    d.polygon([(65, 169), (163, 82), (256, 180)], fill='#405469')
    d.polygon([(0, 171), (96, 151), (182, 177), (256, 157), (256, 256), (0, 256)], fill='#4d7844')
    d.polygon([(142, 166), (158, 166), (193, 256), (93, 256)], fill='#509cba')
    items.append(Fixture('landscape', 'scene', image, 'Continuous sky, mountains, river and tiny sun'))
    sprite = Image.new('RGBA', (24, 24), (0, 0, 0, 0))
    d = ImageDraw.Draw(sprite)
    d.rectangle((5, 7, 18, 19), fill='#244c91')
    d.rectangle((7, 3, 16, 8), fill='#d83b35')
    d.rectangle((7, 10, 9, 12), fill='white')
    d.rectangle((14, 10, 16, 12), fill='white')
    d.rectangle((9, 16, 14, 17), fill='#f5d755')
    items.append(Fixture('pixel-robot', 'pixel', sprite, 'Native 24px pixel art; nearest-neighbour invariance'))
    wire = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(wire)
    d.rectangle((40, 35, 215, 220), outline='#244c91', width=5)
    d.line((42, 130, 213, 130), fill='#d83b35', width=4)
    items.append(Fixture('transparent-thin-frame', 'lineart', wire, 'Sub-cell transparent lines and enclosed negative space'))
    return items
