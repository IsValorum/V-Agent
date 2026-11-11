"""Build native Windows icons and UI logo images from the rounded original artwork.

Source: agent/assets/branding/originals/<palette>.png (2048 px, transparent rounded corners).
"""
from pathlib import Path
from PIL import Image
root=Path(__file__).resolve().parents[1]
icons=root/'desktop/src-tauri/icons'
branding=root/'agent/assets/branding'
for name in ('gold','silver','jade','blue','rose','ruby','violet','ivory'):
    original=Image.open(branding/'originals'/f'{name}.png').convert('RGBA')
    small=original.resize((64,64),Image.Resampling.LANCZOS)
    small.save(icons/f'{name}-original.png')
    (icons/f'{name}.rgba').write_bytes(small.tobytes())
    original.resize((256,256),Image.Resampling.LANCZOS).save(icons/f'{name}.ico',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
    # Interface copy: sharp at 2x for the loading screen, palette cards and favicon.
    original.resize((320,320),Image.Resampling.LANCZOS).save(branding/f'{name}-icon.png',optimize=True)
    if name=='gold':
        original.resize((512,512),Image.Resampling.LANCZOS).save(icons/'icon.png')
        (icons/'icon.ico').write_bytes((icons/'gold.ico').read_bytes())
