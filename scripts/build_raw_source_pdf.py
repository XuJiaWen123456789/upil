"""生成模拟客户原始语料 PDF。

真实机构交付给 RAG 项目的语料通常是宣传册类 PDF：带重复页眉页脚、多栏排版、
跨页表格和图片。本脚本专门模拟这类原始 PDF，用于演示 RAGFlow 的解析链路，
与已清洗的 Markdown 知识源形成对比评测样本。内容全部为虚构演示数据。
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image as PdfImage,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(r"D:\uPil")
OUTPUT_DIR = ROOT / "knowledge_base" / "raw"
OUTPUT_PDF = OUTPUT_DIR / "星河素质教育中心课程宣传册_模拟原始语料.pdf"
ASSET_DIR = ROOT / "knowledge_base" / "pdf" / "assets"


def register_fonts() -> tuple[str, str]:
    """注册中文字体。"""

    regular_path = Path(r"C:\Windows\Fonts\msyh.ttc")
    bold_path = Path(r"C:\Windows\Fonts\msyhbd.ttc")
    if not regular_path.exists():
        regular_path = Path(r"C:\Windows\Fonts\simhei.ttf")
    if not bold_path.exists():
        bold_path = regular_path
    pdfmetrics.registerFont(TTFont("RawChinese", str(regular_path), subfontIndex=0))
    pdfmetrics.registerFont(TTFont("RawChineseBold", str(bold_path), subfontIndex=0))
    return "RawChinese", "RawChineseBold"


def styles(font_regular: str, font_bold: str) -> dict[str, ParagraphStyle]:
    """定义宣传册风格的样式。"""

    base = getSampleStyleSheet()
    return {
        "cover": ParagraphStyle("cover", parent=base["Title"], fontName=font_bold, fontSize=30, leading=42, alignment=TA_CENTER, textColor=colors.HexColor("#24484f"), spaceAfter=10),
        "slogan": ParagraphStyle("slogan", parent=base["Normal"], fontName=font_regular, fontSize=14, leading=24, alignment=TA_CENTER, textColor=colors.HexColor("#527077")),
        "h1": ParagraphStyle("h1", parent=base["Heading1"], fontName=font_bold, fontSize=17, leading=24, textColor=colors.white, backColor=colors.HexColor("#3f7880"), borderPadding=6, spaceBefore=8, spaceAfter=10),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName=font_bold, fontSize=12, leading=18, textColor=colors.HexColor("#2f6870"), spaceBefore=8, spaceAfter=6),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontName=font_regular, fontSize=9.5, leading=16, textColor=colors.HexColor("#263c40"), spaceAfter=5),
        "small": ParagraphStyle("small", parent=base["BodyText"], fontName=font_regular, fontSize=7.5, leading=11, textColor=colors.HexColor("#5b7074"), spaceAfter=3),
        "table": ParagraphStyle("table", parent=base["BodyText"], fontName=font_regular, fontSize=7.4, leading=11, textColor=colors.HexColor("#263c40")),
        "table_head": ParagraphStyle("table_head", parent=base["BodyText"], fontName=font_bold, fontSize=7.8, leading=11, textColor=colors.white, alignment=TA_CENTER),
    }


def P(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def make_table(rows: list[list[str]], widths: list[float], s: dict[str, ParagraphStyle]) -> Table:
    """构造宣传册表格，允许跨页拆分。"""

    converted = []
    for row_index, row in enumerate(rows):
        converted.append([P(value, s["table_head"] if row_index == 0 else s["table"]) for value in row])
    table = Table(converted, colWidths=widths, repeatRows=1, hAlign="LEFT", splitByRow=1)
    commands = [
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#b8c9c7")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3f7880")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
    ]
    table.setStyle(TableStyle(commands))
    return table


def header_footer(canvas, doc) -> None:
    """模拟宣传册常见的重复页眉页脚，这是 PDF 解析中的典型噪声。"""

    canvas.saveState()
    width, height = A4
    canvas.setStrokeColor(colors.HexColor("#d2dfdc"))
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, height - 15 * mm, width - 18 * mm, height - 15 * mm)
    canvas.setFont("RawChinese", 7.5)
    canvas.setFillColor(colors.HexColor("#6a7d80"))
    canvas.drawString(18 * mm, height - 11 * mm, "星河素质教育中心 | 咨询热线 400-000-0000")
    canvas.drawString(18 * mm, 11 * mm, "本宣传册为演示资料，最终解释权归机构所有")
    canvas.drawRightString(width - 18 * mm, 11 * mm, f"第 {doc.page} 页")
    canvas.restoreState()


def add_image(name: str, width: float, height: float) -> PdfImage:
    image = PdfImage(str(ASSET_DIR / name), width=width, height=height, hAlign="CENTER")
    image.hAlign = "CENTER"
    return image


def build_pdf() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    regular, bold = register_fonts()
    s = styles(regular, bold)
    doc = BaseDocTemplate(
        str(OUTPUT_PDF),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=22 * mm,
        bottomMargin=18 * mm,
        title="星河素质教育中心课程宣传册（模拟原始语料）",
        author="星河素质教育中心",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates([PageTemplate(id="all", frames=frame, onPage=header_footer)])
    story = []

    # 封面。
    story += [
        Spacer(1, 30 * mm),
        P("星河素质教育中心", s["cover"]),
        P("2026 秋季课程宣传册", s["cover"]),
        Spacer(1, 8 * mm),
        P("发现兴趣 · 自信成长 · 快乐学习", s["slogan"]),
        Spacer(1, 15 * mm),
        add_image("campus_front_demo.png", 150 * mm, 100 * mm),
        Spacer(1, 12 * mm),
        P("舞蹈 | 美术 | 编程 | 音乐 | 少儿素养", s["slogan"]),
        PageBreak(),
    ]

    # 关于我们。
    story += [
        P("关于我们", s["h1"]),
        P("星河素质教育中心成立于 2016 年，是一家面向 4 至 16 岁学员的素质教育机构，现有专职教师 8 名、教务老师 4 名，开设舞蹈、美术、音乐和少儿编程课程。我们坚持“学中玩、玩中学”的教学理念，注重兴趣培养、过程反馈和家校沟通。", s["body"]),
        P("我们的教育理念", s["h2"]),
        P("兴趣优先：启蒙阶段以游戏、律动和体验为主，先让孩子喜欢课堂。", s["body"]),
        P("过程反馈：定期向家长反馈课堂表现、阶段收获和下一步建议。", s["body"]),
        P("安全第一：关注课堂动作安全、材料安全和接送安全。", s["body"]),
        P("家校沟通：家长可预约面谈，及时了解孩子的学习状态。", s["body"]),
        PageBreak(),
    ]

    # 热门课程。
    story += [
        P("热门课程推荐", s["h1"]),
        make_table([
            ["课程", "适龄", "时长", "课程亮点"],
            ["舞蹈启蒙班", "4-6 岁", "45 分钟", "律动游戏，培养节奏与协调"],
            ["中国舞基础班", "6-12 岁", "60 分钟", "基本功与民族舞组合"],
            ["少儿美术创意班", "5-10 岁", "60 分钟", "观察、色彩与创意表达"],
            ["少儿编程基础班", "8-12 岁", "75 分钟", "图形化编程与项目作品"],
            ["音乐启蒙班", "4-8 岁", "45 分钟", "儿歌律动与打击乐体验"],
            ["童声合唱班", "7-12 岁", "75 分钟", "发声训练与多声部配合"],
        ], [40 * mm, 24 * mm, 28 * mm, 72 * mm], s),
        Spacer(1, 8 * mm),
        P("学习各课程的好处", s["h2"]),
        P("舞蹈培养身体协调、形体气质和自信表达；美术培养观察力、想象力和审美能力；编程培养逻辑思维、问题拆解和专注力；音乐培养音准节奏、听觉记忆和合作能力。", s["body"]),
        PageBreak(),
    ]

    # 完整价目表，行数较多，故意让它跨页，模拟真实宣传册。
    story += [P("课程收费标准", s["h1"]), P("以下为演示价目表，币种为人民币，实际价格以订单和当期活动为准。", s["body"])]
    fee_rows = [
        ["课程", "套餐", "价格", "有效期", "备注"],
        ["舞蹈启蒙班", "12 节", "1,800 元", "4 个月", "赠送试听 1 次"],
        ["舞蹈启蒙班", "24 节", "3,400 元", "8 个月", "含阶段展示"],
        ["中国舞基础班", "24 节", "3,600 元", "8 个月", "含基本功训练"],
        ["中国舞基础班", "48 节", "6,800 元", "14 个月", "含汇演排练"],
        ["中国舞进阶班", "24 节", "4,800 元", "10 个月", "需教师评估"],
        ["少儿美术创意班", "12 节", "1,500 元", "4 个月", "含基础材料"],
        ["少儿美术创意班", "24 节", "2,800 元", "8 个月", "含作品展"],
        ["素描基础班", "16 节", "2,400 元", "6 个月", "含素描工具"],
        ["少儿编程基础班", "16 节", "2,800 元", "6 个月", "含课堂电脑"],
        ["少儿编程基础班", "32 节", "5,200 元", "12 个月", "含项目展示"],
        ["编程项目实践班", "20 节", "4,000 元", "8 个月", "需完成基础学习"],
        ["音乐启蒙班", "12 节", "1,600 元", "4 个月", "含打击乐器体验"],
        ["童声合唱班", "16 节", "2,200 元", "6 个月", "含演出排练"],
        ["童声合唱班", "32 节", "4,000 元", "12 个月", "含登台演出"],
    ]
    story.append(make_table(fee_rows, [34 * mm, 20 * mm, 24 * mm, 24 * mm, 62 * mm], s))
    story.append(Spacer(1, 8 * mm))
    story.append(P("优惠说明：团购、老带新和节假日优惠以当期活动通知为准，本册不固定承诺折扣。", s["body"]))
    story.append(PageBreak())

    # 师资与校区。
    story += [
        P("师资团队", s["h1"]),
        P("林老师：中国舞与舞蹈启蒙，教龄 8 年，课堂节奏明快，擅长用游戏和故事帮助低龄学员理解动作。", s["body"]),
        P("周老师：少儿美术创意，教龄 6 年，鼓励自由表达，重点培养观察力、想象力和表达自信。", s["body"]),
        P("陈老师：少儿编程基础，教龄 5 年，以项目任务驱动，让孩子每节课完成一个可见的小作品。", s["body"]),
        Spacer(1, 8 * mm),
        P("校区地址", s["h1"]),
        P("星河中心校区：示例市星河区育才路 88 号 2 层。可在“育才路儿童活动中心”站下车，具体路线以地图导航为准。", s["body"]),
        P("营业时间：周一至周五 09:00-20:30，周六至周日 08:30-21:00。", s["body"]),
        P("报名咨询：400-000-0000。", s["body"]),
        Spacer(1, 8 * mm),
        P("温馨提示", s["h2"]),
        P("本宣传册为演示资料，课程、价格、教师、地址均为虚构内容，不代表真实机构政策。涉及退费、转课和学员个人课时等问题，请以协议和教务系统为准。", s["body"]),
    ]

    doc.build(story)
    return OUTPUT_PDF


if __name__ == "__main__":
    print(build_pdf())
