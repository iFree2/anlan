"""Program-drawn synthetic diagrams, not photographs or a vision-model result."""

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]


def main():
    out = ROOT / "examples/synthetic/multimodal-v1"
    out.mkdir(parents=True, exist_ok=False)
    cases = []
    font = ImageFont.load_default(size=18)
    for number, hidden in enumerate((False, True), 1):
        picture = Image.new("RGB", (512, 384), "#f5f6f8")
        draw = ImageDraw.Draw(picture)
        draw.text((22, 18), "SYNTHETIC DIAGRAM - NO REAL WORKER", fill="#253345", font=font)
        draw.line((60, 350, 450, 350), fill="#8d99a8", width=3)
        draw.line((222, 280, 213, 349), fill="#253345", width=22)
        draw.line((289, 280, 300, 349), fill="#253345", width=22)
        draw.rounded_rectangle((201, 178, 310, 288), radius=24, fill="#347ab6")
        draw.line((209, 197, 169, 263), fill="#347ab6", width=21)
        draw.line((300, 197, 340, 263), fill="#347ab6", width=21)
        draw.rectangle((245, 162, 268, 191), fill="#edbe9c")
        draw.ellipse((216, 83, 296, 171), fill="#edbe9c", outline="#775039", width=3)
        draw.ellipse((237, 123, 242, 128), fill="#253345")
        draw.ellipse((271, 123, 276, 128), fill="#253345")
        draw.arc((243, 136, 269, 154), 0, 180, fill="#775039", width=2)
        if hidden:
            draw.rectangle((182, 65, 330, 180), fill="#7a8088", outline="#555b65", width=3)
            draw.line((184, 67, 328, 178), fill="#a8afb8", width=3)
            draw.line((328, 67, 184, 178), fill="#a8afb8", width=3)
        name = f"diagram-{number}.png"
        picture.save(out / name, optimize=True)
        cases.append({"id": f"diagram-{number}", "image": name,
                      "image_sha256": hashlib.sha256((out / name).read_bytes()).hexdigest(),
                      "structured": {"data_origin": "SYNTHETIC",
                                     "head_visible": not hidden,
                                     "headwear": None if hidden else "none"},
                      "gold": {"head_observation": "not_visible" if hidden else "bare_head",
                               "requires_human_review": True}})
    data = {"data_origin": "SYNTHETIC", "origin": "program_drawn_geometric_diagrams",
            "label_origin": "AI_authored_fixture_not_independent_human_gold", "cases": cases}
    (out / "manifest.json").write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                       encoding="utf-8")


if __name__ == "__main__":
    main()
