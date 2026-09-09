"""生成星河素质教育中心的卡通演示插图。

本脚本使用 PIL 绘制 Q 版卡通人物和场景图，避免依赖外部图片下载与真实个人照片。
生成的 PNG 同时用于知识库文档引用和 PDF 知识手册排版。
"""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(r"D:\uPil")
MEDIA_DIR = ROOT / "knowledge_base" / "demo_institution" / "media"
ASSET_DIR = ROOT / "knowledge_base" / "pdf" / "assets"


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """选择可用的 Windows 中文字体，保证图片中的文字不乱码。"""

    path = r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc"
    if not os.path.exists(path):
        path = r"C:\Windows\Fonts\simhei.ttf"
    return ImageFont.truetype(path, size=size, index=0)


def draw_teacher_head(
    size: int,
    *,
    hair_color: str,
    clothes_color: str,
    bg_color: str,
    accessory: str,
) -> Image.Image:
    """绘制一张 Q 版卡通教师头像。"""

    img = Image.new("RGB", (size, size), bg_color)
    draw = ImageDraw.Draw(img)

    # 背景装饰圆点，让画面更活泼。
    for x, y, r in [(70, 80, 26), (size - 70, 100, 18), (90, size - 90, 14), (size - 90, size - 80, 22)]:
        draw.ellipse((x - r, y - r, x + r, y + r), fill="#ffffff")

    # 身体：先画衣服和领口，再覆盖头部，形成 Q 版大头比例。
    draw.rounded_rectangle((180, 560, size - 180, size - 40), radius=70, fill=clothes_color)
    draw.ellipse((size // 2 - 55, 545, size // 2 + 55, 645), fill=clothes_color)

    # 头发：根据配饰选择丸子头或短发。
    if accessory == "bun":
        draw.ellipse((size // 2 - 42, 105, size // 2 + 42, 195), fill=hair_color)
        draw.pieslice((220, 120, size - 220, size - 300), 180, 360, fill=hair_color)
    elif accessory == "beret":
        draw.pieslice((210, 130, size - 210, 390), 180, 360, fill=hair_color)
        draw.ellipse((235, 100, size - 235, 260), fill="#c44569")
        draw.ellipse((size // 2 - 20, 65, size // 2 + 20, 105), fill="#c44569")
    else:
        draw.pieslice((210, 130, size - 210, 420), 180, 360, fill=hair_color)

    # 耳朵和脸部。
    draw.ellipse((205, 285, 255, 355), fill="#f2b28c")
    draw.ellipse((size - 255, 285, size - 205, 355), fill="#f2b28c")
    draw.ellipse((210, 160, size - 210, size - 230), fill="#ffe0c4")

    # 刘海。
    draw.pieslice((225, 150, size - 225, 350), 180, 360, fill=hair_color)

    # 眼睛：大而有神。
    for cx in (size // 2 - 80, size // 2 + 80):
        draw.ellipse((cx - 34, 300, cx + 34, 368), fill="#2f3640")
        draw.ellipse((cx - 16, 318, cx + 16, 350), fill="#ffffff")
        draw.ellipse((cx - 8, 325, cx + 4, 340), fill="#2f3640")

    # 眉毛。
    for x1, x2 in [(size // 2 - 130, size // 2 - 40), (size // 2 + 40, size // 2 + 130)]:
        draw.arc((x1, 255, x2, 300), 20, 160, fill=hair_color, width=8)

    # 腮红和微笑。
    draw.ellipse((size // 2 - 160, 420, size // 2 - 70, 480), fill="#ffb3b3")
    draw.ellipse((size // 2 + 70, 420, size // 2 + 160, 480), fill="#ffb3b3")
    draw.arc((size // 2 - 70, 370, size // 2 + 70, 450), 20, 160, fill="#c44569", width=8)

    # 领口装饰。
    draw.ellipse((size // 2 - 45, 560, size // 2 + 45, 640), fill="#ffffff")
    return img


def draw_campus(size: tuple[int, int]) -> Image.Image:
    """绘制卡通校区外景图。"""

    w, h = size
    img = Image.new("RGB", (w, h), "#dff3ff")
    draw = ImageDraw.Draw(img)

    # 天空和太阳。
    draw.ellipse((w - 180, 50, w - 80, 150), fill="#ffd166")
    draw.ellipse((140, 110, 220, 180), fill="#ffffff")
    draw.ellipse((230, 80, 300, 140), fill="#ffffff")

    # 地面。
    draw.rectangle((0, h - 170, w, h), fill="#b9e4c9")

    # 教学楼主体。
    draw.rectangle((180, 230, 960, h - 180), fill="#fff4e0")
    draw.polygon([(130, 260), (570, 80), (1010, 260)], fill="#ff9f68")

    # 门。
    draw.rectangle((500, h - 330, 650, h - 180), fill="#8d6e63")
    draw.ellipse((590, h - 265, 610, h - 245), fill="#fff4e0")

    # 窗户。
    for x in (230, 330, 700, 800):
        draw.rounded_rectangle((x, 330, x + 80, 430), radius=12, fill="#8ecae6")
    for x in (230, 330, 700, 800):
        draw.rounded_rectangle((x, 500, x + 80, 600), radius=12, fill="#8ecae6")

    # 招牌。
    draw.rounded_rectangle((300, 270, 880, 360), radius=18, fill="#5b8fa3")
    draw.text((355, 290), "星河素质教育中心", font=load_font(42, bold=True), fill="#ffffff")

    # 三个卡通小学员。
    for cx, top, color in [(250, h - 150, "#ef476f"), (570, h - 160, "#06d6a0"), (880, h - 140, "#118ab2")]:
        draw.ellipse((cx - 42, top - 85, cx + 42, top), fill="#ffe0c4")
        draw.pieslice((cx - 45, top - 110, cx + 45, top - 30), 180, 360, fill="#4a4e69")
        draw.rounded_rectangle((cx - 55, top, cx + 55, top + 90), radius=30, fill=color)
        draw.ellipse((cx - 24, top - 55, cx - 4, top - 35), fill="#2f3640")
        draw.ellipse((cx + 4, top - 55, cx + 24, top - 35), fill="#2f3640")
        draw.arc((cx - 22, top - 48, cx + 22, top - 12), 20, 160, fill="#c44569", width=5)

    return img


def draw_schedule(size: tuple[int, int]) -> Image.Image:
    """绘制卡通风格周末课程表海报。"""

    w, h = size
    img = Image.new("RGB", (w, h), "#fff7f0")
    draw = ImageDraw.Draw(img)

    # 标题装饰。
    draw.rounded_rectangle((60, 50, w - 60, 150), radius=30, fill="#ff9f68")
    draw.text((120, 72), "周末课程安排示例", font=load_font(52, bold=True), fill="#ffffff")

    # 课程卡片。
    cards = [
        ("舞蹈启蒙", "周六 09:00-09:45", "#ffb3c6"),
        ("中国舞基础", "周六 10:00-11:00", "#ff8fab"),
        ("美术创意", "周六 10:00-11:00", "#a2d2ff"),
        ("编程基础", "周日 10:30-11:30", "#b8e0d2"),
    ]
    for idx, (name, time, color) in enumerate(cards):
        x = 80 + (idx % 2) * 540
        y = 220 + (idx // 2) * 260
        draw.rounded_rectangle((x, y, x + 500, y + 220), radius=30, fill=color)
        draw.text((x + 40, y + 50), name, font=load_font(44, bold=True), fill="#3a3a3a")
        draw.text((x + 40, y + 125), time, font=load_font(34), fill="#555555")

    draw.text((80, 750), "以上为演示课表，实际以教务排课为准", font=load_font(28), fill="#9a8c98")
    return img


def save_both(image: Image.Image, name: str) -> None:
    """把同一张图片保存到知识库媒体目录和 PDF 资源目录。"""

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    for directory in (MEDIA_DIR, ASSET_DIR):
        image.save(directory / f"{name}.png", "PNG")


def main() -> None:
    """生成全部演示插图。"""

    save_both(draw_teacher_head(800, hair_color="#3d2b3d", clothes_color="#ff8fab", bg_color="#ffe3ec", accessory="bun"), "teacher_lina_demo")
    save_both(draw_teacher_head(800, hair_color="#4a2c2a", clothes_color="#a2d2ff", bg_color="#e3f2fd", accessory="beret"), "teacher_zhou_demo")
    save_both(draw_teacher_head(800, hair_color="#1f2937", clothes_color="#b8e0d2", bg_color="#e6f7f1", accessory="glasses"), "teacher_chen_demo")
    save_both(draw_campus((1200, 800)), "campus_front_demo")
    save_both(draw_schedule((1200, 800)), "schedule_demo")
    print("generated 5 demo assets")


if __name__ == "__main__":
    main()
