"""Count repaints while the interface is idle: the check behind the "windows flicker" fixes.

The browser's screencast sends a frame each time something is repainted. With a window open and
nothing happening, the only frames should be the text caret blinking. For every scene this prints
how many frames arrived and the area that changed in each; a window repainting on its own (for
example every 2.5 s with the statistics poll, as a live backdrop blur did) shows up at once.
Before/after images of the first change are saved to build/repaint-probe/.

    .venv\\Scripts\\python tests\\smoke\\repaint_probe.py --idle 8

Needs a running core (see tests/README.md) and Pillow. Exit code 1 when a window repaints while idle.
"""
import argparse
import asyncio
import base64
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from headless import ROOT, Browser  # noqa: E402

CLOSE = ("document.getElementById('closeControls')?.click();"
         "document.querySelectorAll('.fw [data-fw-close]').forEach(b=>b.offsetParent&&b.click());"
         "await new Promise(r=>setTimeout(r,400));")
SCENES = [
    ('idle', ''),
    ('model-window', "document.getElementById('modelBtn').click();"),
    ('tools-window', CLOSE + "document.getElementById('mcpBtn').click();"),
    ('settings', CLOSE + "document.getElementById('gear').click();"),
    ('models-window', "document.getElementById('gear').click();await new Promise(r=>setTimeout(r,400));"
                      "document.getElementById('sidebarModels').click();"),
]
# Smaller than this is a blinking caret or a number redrawn with the same value: not visible.
TINY = 10


async def probe(url, idle, out):
    from PIL import Image, ImageChops
    out.mkdir(parents=True, exist_ok=True)
    noisy = []
    async with Browser() as browser:
        await browser.open(url)
        for name, script in SCENES:
            if script:
                await browser.run(script)
            await asyncio.sleep(2.5)  # opening animations end first
            browser.frames.clear()
            await browser.call('Page.startScreencast', {'format': 'png', 'everyNthFrame': 1})
            await asyncio.sleep(idle)
            await browser.call('Page.stopScreencast')
            await asyncio.sleep(.3)
            images = [(t, Image.open(io.BytesIO(base64.b64decode(d))).convert('RGB')) for t, d in browser.frames]
            changes = []
            for (_, before), (when, after) in zip(images, images[1:]):
                box = ImageChops.difference(before, after).getbbox()
                if box and (box[2] - box[0] >= TINY or box[3] - box[1] >= TINY) and (box[2] - box[0]) * (box[3] - box[1]) >= TINY * TINY:
                    changes.append((round(when - images[0][0], 2), box, before, after))
            print(f'{name}: {len(images)} frames in {idle:g} s idle, {len(changes)} visible changes (caret and same-value redraws ignored)')
            for when, box, _, _ in changes[:8]:
                print(f'    t={when}s area={box}')
            if changes:
                changes[0][2].save(out / f'{name}-before.png')
                changes[0][3].save(out / f'{name}-after.png')
                # One change right after opening is the window settling; repeated ones are flicker.
                if len(changes) > 1:
                    noisy.append(name)
    print('Windows repainting while idle:', noisy or 'none')
    return 1 if noisy else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--url', default='http://127.0.0.1:19381/')
    parser.add_argument('--idle', type=float, default=8, help='seconds to watch each scene')
    parser.add_argument('--out', default=str(ROOT / 'build' / 'repaint-probe'))
    args = parser.parse_args()
    sys.exit(asyncio.run(probe(args.url, args.idle, Path(args.out))))


if __name__ == '__main__':
    main()
