from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "output" / "playwright" / "icon-1024.png"


def main():
    image = Image.open(SOURCE).convert("RGBA")

    image.resize((512, 512), Image.Resampling.LANCZOS).save(
        ROOT / "icon-512.png", format="PNG", optimize=True
    )
    image.resize((256, 256), Image.Resampling.LANCZOS).save(
        ROOT / "icon-256.png", format="PNG", optimize=True
    )

    image.save(
        ROOT / "icon.ico",
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
               (64, 64), (128, 128), (256, 256)],
    )
    image.resize((256, 256), Image.Resampling.LANCZOS).save(
        ROOT / "site" / "favicon.png", format="PNG", optimize=True
    )


if __name__ == "__main__":
    main()
