"""Walk through the interface of a running core and save a full screenshot after every step.

Each step is [name, javascript, seconds_to_wait]; the JavaScript runs as an async function body in the
page and may return a short text (printed next to the step name) — use it to report what the screen
shows so it can be compared with what the core says. The special script "@reload" reloads the page,
to check what survives a restart. Page errors and console errors are reported at the end.

    .venv\\Scripts\\python backend.py --port 19381 --data-dir %TEMP%\\v-agent-ui -- --background
    .venv\\Scripts\\python tests\\smoke\\ui_walkthrough.py tests\\smoke\\ui_steps.json --size 800x600 --scheme light

Screenshots go to build/ui-walkthrough/. Exit code 1 when the page reported errors or a step failed.
"""
import argparse
import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from headless import ROOT, Browser  # noqa: E402


async def walk(steps, url, width, height, scheme, out):
    out.mkdir(parents=True, exist_ok=True)
    failed = []
    async with Browser(width, height, scheme) as browser:
        await browser.open(url)
        for name, script, wait in steps:
            try:
                if script == '@reload':
                    await browser.call('Page.reload')
                    await asyncio.sleep(4.5)
                elif script:
                    value = await browser.run(script)
                    if value not in (None, ''):
                        print(f'  {name}: {value}')
            except RuntimeError as error:
                failed.append(f'{name}: {error}')
            await asyncio.sleep(wait)
            shot = await browser.call('Page.captureScreenshot', {'format': 'png'})
            (out / f'{name}.png').write_bytes(base64.b64decode(shot['data']))
        problems = failed + browser.errors
    print('Page errors:', problems or 'none')
    print('Screenshots:', out)
    return 1 if problems else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('steps', help='JSON file: [[name, javascript, seconds], ...]')
    parser.add_argument('--url', default='http://127.0.0.1:19381/')
    parser.add_argument('--size', default='1280x800', help='window size, e.g. 800x600 (the smallest window allowed is 760x480)')
    parser.add_argument('--scheme', default='dark', choices=('dark', 'light'))
    parser.add_argument('--out', default=str(ROOT / 'build' / 'ui-walkthrough'))
    args = parser.parse_args()
    width, height = (int(x) for x in args.size.lower().split('x'))
    steps = json.loads(Path(args.steps).read_text(encoding='utf-8'))
    sys.exit(asyncio.run(walk(steps, args.url, width, height, args.scheme, Path(args.out))))


if __name__ == '__main__':
    main()
