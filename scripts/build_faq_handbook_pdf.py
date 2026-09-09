"""生成星河素质教育中心家长服务手册 PDF。

本脚本生成面向家长阅读的原生机构手册，只包含星河素质教育中心的相关内容，
不包含任何系统实现细节。全部图片使用本地绘制的卡通演示插图，所有课程、
价格、教师、地址和活动均为虚构演示内容。
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
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(r"D:\uPil")
OUTPUT_DIR = ROOT / "knowledge_base" / "pdf"
ASSET_DIR = OUTPUT_DIR / "assets"
OUTPUT_PDF = OUTPUT_DIR / "星河素质教育中心家长服务与课程知识手册_完整版.pdf"


def register_fonts() -> tuple[str, str]:
    """注册 Windows 中文字体，保证 PDF 中的中文可复制且不乱码。"""

    regular_path = Path(r"C:\Windows\Fonts\msyh.ttc")
    bold_path = Path(r"C:\Windows\Fonts\msyhbd.ttc")
    if not regular_path.exists():
        regular_path = Path(r"C:\Windows\Fonts\simhei.ttf")
    if not bold_path.exists():
        bold_path = regular_path
    pdfmetrics.registerFont(TTFont("XHChinese", str(regular_path), subfontIndex=0))
    pdfmetrics.registerFont(TTFont("XHChineseBold", str(bold_path), subfontIndex=0))
    return "XHChinese", "XHChineseBold"


def styles(font_regular: str, font_bold: str) -> dict[str, ParagraphStyle]:
    """定义全篇一致的标题、正文、表格和提示样式。"""

    base = getSampleStyleSheet()
    return {
        "cover_title": ParagraphStyle("cover_title", parent=base["Title"], fontName=font_bold, fontSize=27, leading=38, alignment=TA_CENTER, textColor=colors.HexColor("#24484f"), spaceAfter=10),
        "cover_subtitle": ParagraphStyle("cover_subtitle", parent=base["Normal"], fontName=font_regular, fontSize=14, leading=24, alignment=TA_CENTER, textColor=colors.HexColor("#527077")),
        "h1": ParagraphStyle("h1", parent=base["Heading1"], fontName=font_bold, fontSize=18, leading=25, textColor=colors.HexColor("#24484f"), spaceBefore=8, spaceAfter=10),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName=font_bold, fontSize=13, leading=19, textColor=colors.HexColor("#2f6870"), spaceBefore=8, spaceAfter=6),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontName=font_regular, fontSize=9.5, leading=16, textColor=colors.HexColor("#263c40"), spaceAfter=5),
        "small": ParagraphStyle("small", parent=base["BodyText"], fontName=font_regular, fontSize=7.5, leading=11, textColor=colors.HexColor("#5b7074"), spaceAfter=3),
        "callout": ParagraphStyle("callout", parent=base["BodyText"], fontName=font_regular, fontSize=9, leading=15, textColor=colors.HexColor("#29464c"), backColor=colors.HexColor("#edf5f3"), borderColor=colors.HexColor("#9fc4be"), borderWidth=0.7, borderPadding=8, spaceBefore=5, spaceAfter=8),
        "table": ParagraphStyle("table", parent=base["BodyText"], fontName=font_regular, fontSize=7.4, leading=11, textColor=colors.HexColor("#263c40")),
        "table_head": ParagraphStyle("table_head", parent=base["BodyText"], fontName=font_bold, fontSize=7.8, leading=11, textColor=colors.white, alignment=TA_CENTER),
        "qa": ParagraphStyle("qa", parent=base["BodyText"], fontName=font_regular, fontSize=8.8, leading=14, textColor=colors.HexColor("#263c40"), spaceAfter=6),
        "teacher_name": ParagraphStyle("teacher_name", parent=base["Heading2"], fontName=font_bold, fontSize=12, leading=18, textColor=colors.HexColor("#24484f")),
    }


def P(text: str, style: ParagraphStyle) -> Paragraph:
    """构造段落并统一处理少量 HTML 标记。"""

    return Paragraph(text, style)


def make_table(rows: list[list[str]], widths: list[float], s: dict[str, ParagraphStyle], header: bool = True) -> Table:
    """构造带表头、斑马纹和内边距的中文表格。"""

    converted = []
    for row_index, row in enumerate(rows):
        converted.append([P(value, s["table_head"] if header and row_index == 0 else s["table"]) for value in row])
    table = Table(converted, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    commands = [
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#b8c9c7")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if header:
        commands.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3f7880")))
        commands.append(("TEXTCOLOR", (0, 0), (-1, 0), colors.white))
        for row_index in range(1, len(rows)):
            if row_index % 2 == 0:
                commands.append(("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#f4f8f7")))
    table.setStyle(TableStyle(commands))
    return table


def header_footer(canvas, doc) -> None:
    """绘制统一页眉、页脚和页码。"""

    canvas.saveState()
    width, height = A4
    canvas.setStrokeColor(colors.HexColor("#d2dfdc"))
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, height - 15 * mm, width - 18 * mm, height - 15 * mm)
    canvas.setFont("XHChinese", 7.5)
    canvas.setFillColor(colors.HexColor("#6a7d80"))
    canvas.drawString(18 * mm, height - 11 * mm, "星河素质教育中心 | 家长服务与课程知识手册")
    canvas.drawRightString(width - 18 * mm, 11 * mm, f"第 {doc.page} 页")
    canvas.drawString(18 * mm, 11 * mm, "虚构演示资料 | 版本 demo-2026-09-01")
    canvas.restoreState()


def add_image(name: str, width: float, height: float) -> PdfImage:
    """加载本地卡通插图并缩放到稳定尺寸。"""

    image = PdfImage(str(ASSET_DIR / name), width=width, height=height, hAlign="CENTER")
    image.hAlign = "CENTER"
    return image


def teacher_block(
    image_name: str,
    name: str,
    direction: str,
    years: str,
    background: str,
    resume: list[str],
    style_text: str,
    idea: str,
    keywords: str,
    topics: str,
    s: dict[str, ParagraphStyle],
):
    """构造一位教师的头像、简介和履历区块。"""

    block = [
        add_image(image_name, 34 * mm, 34 * mm),
        Spacer(1, 2 * mm),
        P(name, s["teacher_name"]),
        make_table(
            [
                ["主教方向", direction],
                ["教龄", years],
                ["专业背景", background],
                ["教学履历", "；".join(resume)],
                ["授课风格", style_text],
                ["教学理念", idea],
                ["家长评价关键词", keywords],
                ["适合咨询的问题", topics],
            ],
            [30 * mm, 134 * mm],
            s,
        ),
        Spacer(1, 5 * mm),
    ]
    return block


def build_pdf() -> Path:
    """生成完整 PDF 手册。"""

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
        title="星河素质教育中心家长服务与课程知识手册（演示版）",
        author="星河素质教育中心",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates([PageTemplate(id="all", frames=frame, onPage=header_footer)])
    story = []

    # 封面：机构名称、手册用途和卡通校区插图。
    story += [
        Spacer(1, 30 * mm),
        P("星河素质教育中心", s["cover_title"]),
        P("家长服务与课程知识手册", s["cover_title"]),
        Spacer(1, 8 * mm),
        P("让每个孩子都能找到适合自己的成长方式", s["cover_subtitle"]),
        Spacer(1, 15 * mm),
        add_image("campus_front_demo.png", 150 * mm, 100 * mm),
        Spacer(1, 12 * mm),
        P("本手册为演示版，全部课程、价格、教师、地址和活动均为虚构内容，<br/>不代表任何真实机构政策。", s["callout"]),
        Spacer(1, 20 * mm),
        P("版本：demo-2026-09-01", s["cover_subtitle"]),
        PageBreak(),
    ]

    # 第一章：关于我们。
    story += [
        P("第一章 关于我们", s["h1"]),
        P("星河素质教育中心面向 4 至 16 岁学员，提供舞蹈、美术、音乐和少儿编程课程。我们相信，素质教育的目标不是让孩子赢在起跑线，而是帮助他们在兴趣中发现自己的节奏，在练习中建立自信，在表达中学会沟通。", s["body"]),
        P("课程设计按照年龄、基础和学习目标进行分层，不把一次试听或一次测评结果当作对学员长期能力的结论。教师负责教学判断，教务负责排课与记录，课程顾问负责需要人工确认的报名和续班沟通。", s["body"]),
        P("我们的教育理念", s["h2"]),
        make_table([
            ["理念", "具体做法"],
            ["兴趣优先", "启蒙阶段以游戏、律动和体验为主，先让孩子喜欢课堂"],
            ["过程反馈", "定期向家长反馈课堂表现、阶段收获和下一步建议"],
            ["安全第一", "关注课堂动作安全、材料安全和接送安全"],
            ["家校沟通", "家长可预约面谈，及时了解孩子的学习状态"],
            ["不唯结果", "不承诺升学、获奖或考级结果，重在持续成长"],
        ], [30 * mm, 134 * mm], s),
        Spacer(1, 5 * mm),
        P("服务承诺", s["h2"]),
        P("我们会清晰说明课程内容、收费标准、请假补课和退费流程；涉及学员个人的课时、出勤和缴费信息，只有家长登录后由教务系统查询，不会仅凭客服口头估计。", s["callout"]),
        PageBreak(),
    ]

    # 第二章：课程体系。
    story += [
        P("第二章 课程体系与适龄建议", s["h1"]),
        P("课程建议采用“年龄范围 + 基础要求 + 学习目标 + 课堂准备 + 进阶条件”的结构，方便家长快速了解孩子适合的方向。", s["body"]),
        make_table([
            ["课程", "建议年龄", "单节时长", "核心目标", "进阶或限制"],
            ["舞蹈启蒙", "4 至 6 岁", "45 分钟", "节奏感、协调性和舞蹈表达", "最终以试听中的注意力和协调性观察为准"],
            ["中国舞基础", "6 至 12 岁", "60 分钟", "基本功、民族舞动作和舞台表现", "进入进阶班需结合基础、教师建议和班级容量"],
            ["中国舞进阶", "8 至 16 岁", "90 分钟", "技术规范、表现力和舞台综合能力", "需在基础班完成 1 至 2 年学习或通过评估"],
            ["少儿美术创意", "5 至 10 岁", "60 分钟", "观察、造型、色彩和创意表达", "特殊材料按当期通知准备"],
            ["素描基础", "10 至 14 岁", "90 分钟", "透视、明暗和造型基本方法", "能专注完成 90 分钟课堂练习"],
            ["少儿编程基础", "8 至 12 岁", "75 分钟", "顺序、循环、条件和简单项目设计", "需能阅读简单中文指令并完成基础电脑操作"],
            ["编程项目实践", "10 至 14 岁", "90 分钟", "需求分析、模块拆解、调试和展示", "需完成图形化编程基础或通过评估"],
            ["音乐启蒙", "4 至 8 岁", "45 分钟", "音准、节奏感和音乐兴趣", "以儿歌律动和节奏游戏为主"],
            ["童声合唱", "7 至 12 岁", "75 分钟", "发声、多声部配合和舞台演唱", "建议每周 1 次"],
        ], [26 * mm, 20 * mm, 20 * mm, 58 * mm, 40 * mm], s),
        Spacer(1, 8 * mm),
        P("学习各课程的好处", s["h2"]),
        make_table([
            ["课程方向", "重点培养能力", "家长关注点"],
            ["舞蹈", "身体协调、形体气质、节奏感、自信表达、坚持", "孩子是否喜欢动、愿意登台展示"],
            ["美术", "观察力、想象力、审美、手脑协调、专注", "孩子是否喜欢观察和动手创作"],
            ["编程", "逻辑思维、问题拆解、专注力、抗挫、表达", "孩子是否喜欢动脑和完成作品"],
            ["音乐与合唱", "音准节奏、听觉记忆、合作倾听", "孩子是否喜欢唱歌、对声音敏感"],
            ["项目实践", "工程思维、动手能力、创新意识", "孩子是否喜欢把想法做成作品"],
        ], [30 * mm, 72 * mm, 62 * mm], s),
        Spacer(1, 6 * mm),
        P("舞蹈：在律动和基本功练习中，孩子逐步学会控制身体、跟随音乐，并通过课堂展示获得自信。", s["body"]),
        P("美术：在观察和创作中，孩子学会注意细节、表达想法，作品没有标准答案，重点是愿意表达。", s["body"]),
        P("编程：把大问题拆成小步骤，在调试中学会耐心和修正，完成作品后向同伴讲解设计思路。", s["body"]),
        Spacer(1, 5 * mm),
        P("课程选择问答", s["h2"]),
        P("Q：孩子没有舞蹈基础，可以报名舞蹈启蒙吗？<br/>A：可以先按 4 至 6 岁启蒙方向了解课程。年龄只是建议范围，最终是否适合要结合试听时的注意力、身体协调和教师观察，不能只根据年龄做确定性判断。", s["qa"]),
        P("Q：8 岁孩子应该选中国舞基础还是舞蹈启蒙？<br/>A：可以优先了解中国舞基础，但仍需要结合既往学习经历、可上课时间和班级容量。客服可以提供初步建议，插班或进阶由教师和教务确认。", s["qa"]),
        P("Q：编程课需要提前买电脑吗？<br/>A：课堂设备和基础软件由机构提供，试听前无需购买电脑。若课后练习需要家庭设备，以当期课程通知中的系统要求为准。", s["qa"]),
        P("Q：课程会保证孩子获奖或通过考级吗？<br/>A：不能保证。客服可以说明课程目标、练习内容和报名流程，考级、比赛和学习效果取决于活动安排、个人投入和相关机构规则。", s["qa"]),
        PageBreak(),
    ]

    # 第三章：师资团队。
    story += [
        P("第三章 师资团队", s["h1"]),
        P("星河素质教育中心现有专职教师 8 名、教务老师 4 名。每位教师均经过试讲、课堂观察和带班实践后独立授课，新教师通常先以助教身份参与课堂。以下为三位演示教师介绍，均为虚构内容。", s["body"]),
    ]
    story += teacher_block(
        "teacher_lina_demo.png",
        "林老师",
        "中国舞与舞蹈启蒙",
        "8 年",
        "毕业于艺术院校舞蹈表演专业，持有中国舞教师资格相关培训证书",
        [
            "曾任少儿艺术团舞蹈教师，负责 4 至 12 岁学员的启蒙与基础教学",
            "连续多年带队参加市级少儿舞蹈展演，编排过儿童群舞、独舞等节目",
            "多次参与机构内部教师培训和课堂观察评分",
        ],
        "课堂节奏明快，擅长用游戏和故事帮助低龄学员理解动作；基本功训练强调动作规范与安全，不要求学员完成超出身体准备的高难度动作",
        "先建立兴趣和身体自信，再循序渐进提升技术；每个孩子的身体发育节奏不同，不与别人比较",
        "耐心、讲解清楚、课堂气氛好、关注安全",
        "舞蹈课程适龄建议、课堂着装准备、阶段学习目标、演出与考级安排",
        s,
    )
    story += teacher_block(
        "teacher_zhou_demo.png",
        "周老师",
        "少儿美术创意与色彩造型",
        "6 年",
        "美术教育专业毕业，持有美术教师资格相关证书",
        [
            "曾在少儿美术工作室担任主课教师，负责 5 至 12 岁学员的创意绘画课程",
            "指导学员参与过区级少儿绘画比赛与机构作品展",
            "擅长将观察训练融入生活主题，例如自然、节日和家庭场景",
        ],
        "鼓励学员自由表达，先观察再创作；课堂上通过提问引导学员描述自己的画面，而不是只追求画得像",
        "美术没有标准答案，重点培养观察能力、想象力和表达自信",
        "启发式教学、孩子愿意表达、作品有想法",
        "美术材料准备、作品展示安排、不同年龄段课程内容、课后练习建议",
        s,
    )
    story += teacher_block(
        "teacher_chen_demo.png",
        "陈老师",
        "少儿编程基础与项目实践",
        "5 年",
        "计算机相关专业毕业，持有青少年编程教育相关培训证书",
        [
            "曾在科技教育机构担任编程主讲教师，负责图形化编程和基础项目课程",
            "参与设计过动画故事、小游戏、数学图形等少儿编程项目主题",
            "多次担任机构编程冬令营和夏令营主讲",
        ],
        "以项目任务驱动，每节课让学员完成一个可见的小作品；讲解时先演示再拆解步骤，鼓励学员自己调试",
        "编程是解决问题的工具，重点培养逻辑思维、耐心和试错能力，而不是只记指令",
        "条理清晰、孩子有成就感、注重动手",
        "编程适龄与基础要求、设备准备、课后练习、项目学习安排",
        s,
    )
    story += [
        P("师资管理与家长须知", s["h2"]),
        P("教师排课会结合班级容量、课程阶段和学员特点安排，机构不保证固定教师不变化。教师请假或临时调课时，机构会安排具备同等教学能力的教师代课，并提前通知家长。涉及教师个人学历、证书编号、联系方式等隐私信息，不对家长公开。", s["body"]),
        PageBreak(),
    ]

    # 第四章：校区环境。
    story += [
        P("第四章 校区环境与到访指引", s["h1"]),
        add_image("campus_front_demo.png", 150 * mm, 100 * mm),
        P("图 1　星河中心校区卡通环境图。图片用于说明空间类型，不作为实时教室安排或安全判断的依据。", s["small"]),
        Spacer(1, 4 * mm),
        P("星河中心校区位于示例市星河区育才路 88 号 2 层，建筑面积约 800 平方米，设置以下功能区：", s["body"]),
        make_table([
            ["功能区", "设施与服务"],
            ["前台接待区", "课程咨询、签到、缴费、失物招领"],
            ["舞蹈教室", "专业舞蹈地胶、把杆、镜面和音响设备"],
            ["美术活动区", "可清洗桌面、水槽、作品晾晒区和材料收纳柜"],
            ["编程教室", "学员电脑、投影设备和作品展示屏"],
            ["音乐教室", "电钢琴、打击乐器和合唱排练区"],
            ["家长休息区", "座椅、饮水机、课程安排公示屏和无线网络"],
            ["安全设施", "灭火器、应急照明、监控设备、急救箱和疏散指示"],
        ], [34 * mm, 130 * mm], s),
        Spacer(1, 5 * mm),
        P("到访与咨询流程", s["h2"]),
        P("1. 在前台登记学员年龄、意向课程、可上课时间段和既往学习经历。<br/>2. 由课程顾问介绍课程内容、课时安排和收费标准。<br/>3. 预约试听或入学评估，确认具体日期和时段。<br/>4. 试听或评估后，由课程顾问反馈结果并确认是否适合报读。<br/>5. 确认报读后，签订课程协议并办理缴费。", s["body"]),
        P("安全提示", s["h2"]),
        P("低龄学员需由家长或监护人接送，不得独自离开校区。家长委托他人接送时，应提前告知教务老师并核对接送人信息。学员如有过敏、慢性疾病或其他需要特别关注的情况，请提前告知教务老师。", s["callout"]),
        PageBreak(),
    ]

    # 第五章：报名收费与退费。
    story += [
        P("第五章 报名、收费与退费", s["h1"]),
        P("以下为演示环境的标准价目，币种为人民币。优惠、团购、赠课和临时活动价格不在本手册中固定承诺，必须以订单和当期活动通知为准。", s["body"]),
        make_table([
            ["课程", "套餐", "演示价格", "有效期"],
            ["舞蹈启蒙班", "12 节", "1,800 元", "4 个月"],
            ["中国舞基础班", "24 节", "3,600 元", "8 个月"],
            ["中国舞进阶班", "24 节", "4,800 元", "10 个月"],
            ["少儿美术创意班", "12 节", "1,500 元", "4 个月"],
            ["素描基础班", "16 节", "2,400 元", "6 个月"],
            ["少儿编程基础班", "16 节", "2,800 元", "6 个月"],
            ["编程项目实践班", "20 节", "4,000 元", "8 个月"],
            ["音乐启蒙班", "12 节", "1,600 元", "4 个月"],
            ["童声合唱班", "16 节", "2,200 元", "6 个月"],
        ], [40 * mm, 24 * mm, 30 * mm, 70 * mm], s),
        Spacer(1, 8 * mm),
        P("标准报名流程", s["h2"]),
        P("1. 家长提交课程方向、年龄、可上课时间和试听需求。<br/>2. 课程顾问确认适龄范围、可选时间和试听安排。<br/>3. 试听后确认班级、套餐和服务条款。<br/>4. 家长完成支付并签署课程服务确认。<br/>5. 教务建立报名记录，家长可通过服务渠道查询排课信息。", s["body"]),
        P("支付方式", s["h2"]),
        P("支持前台缴费和机构指定的线上缴费渠道。家长应通过机构官方渠道完成支付，不向个人账户转账。缴费完成后请保留订单编号和支付凭证，便于后续查询。", s["body"]),
        P("退费与转课说明", s["h2"]),
        P("在未消课且未领取专属材料的情况下，可以提交退费申请；已消课、已领取不可回收材料或存在特殊优惠的订单，需要根据订单条款核算。客服不能直接承诺最终金额和到账时间。转课通常需要原课程仍在有效期内、目标班级有容量，并由教师或教务确认；跨课程、跨校区和历史订单必须人工核验。", s["callout"]),
        P("提交退费申请时，家长需要提供订单编号和申请原因，不应在公开客服对话中提交银行卡密码、短信验证码或完整身份证号码。", s["body"]),
        PageBreak(),
    ]

    # 第六章：请假补课调课。
    story += [
        P("第六章 请假、补课与调课", s["h1"]),
        make_table([
            ["事项", "家长操作", "机构规则", "注意事项"],
            ["请假", "尽量在课前 4 小时提交学员、课程、日期和原因", "是否计入有效请假由教务根据实际情况审核", "临时突发情况可先联系客服说明"],
            ["补课", "有效期内按确认安排参加", "同课程或相近课程有名额、不超有效期", "提交请假不等于补课预约成功"],
            ["调课", "选择同校区目标班级并等待确认", "目标班级有容量、课程等级和年龄匹配", "历史课次修改需转人工"],
            ["机构停课", "查看当期通知", "按实际情况顺延、补课或其他处理", "不套用学员个人请假规则"],
        ], [24 * mm, 46 * mm, 52 * mm, 42 * mm], s),
        Spacer(1, 9 * mm),
        P("周末课程安排示例", s["h2"]),
        add_image("schedule_demo.png", 165 * mm, 110 * mm),
        P("图 2　周末课程安排演示表。该图用于展示课程时段样式，不能回答实时教室、剩余名额或指定学员位置。", s["small"]),
        P("家长咨询提示", s["h2"]),
        P("家长咨询“某学员是否已经请假成功”“是否还有补课名额”或“剩余几次补课”时，需要登录后由教务系统查询，客服不能仅凭规则文档推测结果。", s["callout"]),
        PageBreak(),
    ]

    # 第七章：装备与活动。
    story += [
        P("第七章 装备准备与活动服务", s["h1"]),
        P("课程装备建议", s["h2"]),
        make_table([
            ["课程", "装备建议", "机构提供"],
            ["舞蹈启蒙", "运动服、软底舞蹈鞋、水壶", "课堂音响与教学道具"],
            ["中国舞基础", "练功服、舞蹈鞋，长发扎起", "把杆、地胶和课堂辅助用品"],
            ["少儿美术创意", "可自带围裙或穿旧衣物", "基础纸张、铅笔、橡皮和彩笔"],
            ["素描基础", "无需提前购买", "铅笔、橡皮、素描纸"],
            ["少儿编程", "无需自带电脑", "课堂电脑和基础软件"],
            ["音乐启蒙与合唱", "无需自带乐器", "电钢琴和打击乐器"],
        ], [36 * mm, 68 * mm, 60 * mm], s),
        Spacer(1, 7 * mm),
        P("常见活动", s["h2"]),
        P("机构可能组织阶段作品展示、节日汇演、绘画作品展、编程项目展示和公开体验课。活动是否举办、报名条件、费用、服装要求和家长入场安排，以当期活动通知为准。", s["body"]),
        P("客服服务时间", s["h2"]),
        P("常规人工客服时间为周一至周日 09:00-21:00。非服务时间可以先提交留言，工作人员将在下一个服务时段处理。涉及安全事故、突发伤情或其他紧急事项时，应优先联系现场工作人员和当地紧急服务，不应只等待客服回复。", s["body"]),
        P("需要人工处理的情况", s["h2"]),
        P("退费金额争议、特殊优惠核算、历史课次或出勤记录修改、投诉与服务争议、隐私申诉、资料未覆盖或存在冲突、家长明确要求人工沟通时，客服会登记工单并转由专人跟进。", s["callout"]),
        PageBreak(),
    ]

    # 第八章：学员阶段成果与展示。
    story += [
        P("第八章 学员阶段成果与展示", s["h1"]),
        P("星河素质教育中心重视过程反馈，每 8 至 12 次课为一个阶段，教师会结合课堂观察，向家长反馈出勤与课堂参与情况、本阶段学习目标完成情况、孩子的进步表现和需要继续练习的内容、下一阶段学习建议，以及需要家长配合的事项。", s["body"]),
        P("阶段反馈不是排名，也不对学员进行简单的好坏评价。家长如需更详细了解，可以预约教师或教务一对一面谈。", s["callout"]),
        P("作品与展示", s["h2"]),
        P("舞蹈课程通过课堂小展示、节日汇演和开放日组合展示学习成果；美术课程通过作品墙、绘画作品展和线上作品集展示作品；编程课程通过项目展示会，由学员上台讲解自己的作品；音乐课程通过合唱排练和演出展示学习成果。作品展示以鼓励为主，是否参加展示尊重学员和家长意愿，机构不会未经授权公开学员作品、照片或姓名。", s["body"]),
        P("家长开放日", s["h2"]),
        P("机构不定期举办家长开放日，家长可以预约进入课堂观摩。开放日安排、人数限制和观摩规则以当期通知为准。日常课程通常不安排家长进入教室，以免影响课堂秩序。", s["body"]),
        P("学习报告示例", s["h2"]),
        make_table([
            ["项目", "内容"],
            ["学员", "示例学员"],
            ["课程", "中国舞基础班"],
            ["阶段", "第 1 至 8 次课"],
            ["课堂表现", "能跟随完成基础律动，节奏感有进步"],
            ["进步表现", "体态更挺拔，敢于在小组前展示"],
            ["继续练习", "基本功软开度需要循序练习，不过度追求幅度"],
            ["下阶段建议", "继续保持每周 2 次课，按教师指导完成课后拉伸"],
        ], [30 * mm, 134 * mm], s),
        Spacer(1, 5 * mm),
        P("上述报告为演示样式，真实学习报告以教务系统记录和教师反馈为准。家长不应仅以一次展示或一次比赛结果判断孩子的全部进步，持续投入和兴趣保持同样重要。", s["body"]),
        PageBreak(),
    ]

    # 第九章：安全与健康管理。
    story += [
        P("第九章 安全与健康管理", s["h1"]),
        P("接送安全", s["h2"]),
        P("低龄学员需由家长或监护人接送，不得独自离开校区。家长委托他人接送时，应提前告知教务老师并核对接送人信息。家长迟到接学员时，学员应在家长休息区或前台等候，工作人员会协助看护并联系家长。", s["body"]),
        P("课堂安全", s["h2"]),
        P("舞蹈课教师根据学员身体条件安排基本功训练，不要求学员完成超出身体准备的高难度动作；美术课涉及剪裁工具和特殊材料时，教师先讲解使用方法和安全事项；编程课课堂电脑由机构统一管理；音乐课使用乐器和音响设备时遵守课堂秩序，不追逐打闹。", s["body"]),
        P("健康与过敏管理", s["h2"]),
        P("学员如有过敏、慢性疾病或其他需要特别关注的情况，请家长在报名和开课前告知教务老师。需要携带药品的学员，家长应提前说明用药要求和紧急联系人。课堂中如出现身体不适，教师会先停止训练并联系前台和家长，必要时拨打当地紧急电话。", s["body"]),
        P("应急预案", s["h2"]),
        P("校区配备灭火器、应急照明、急救箱和疏散指示，走廊保持畅通，定期开展消防疏散演练。发生突发伤情时，先进行基础处理并联系家长，伤情较重时立即送医或拨打当地紧急电话。", s["body"]),
        P("隐私保护", s["h2"]),
        P("学员照片、身份证件、家庭住址和联系方式等个人信息不得进入公开手册；作品、照片、报名名单和联系方式属于学员或家庭资料，必须经过授权并按可见范围展示；家长咨询时不需要提交银行卡密码、短信验证码或与当前问题无关的敏感信息。", s["callout"]),
        PageBreak(),
    ]

    # 第十章：家长常见 FAQ。
    story += [P("第十章 家长常见问题 FAQ", s["h1"]), P("以下为家长经常咨询的问题和回答，均为演示内容。", s["body"])]
    faq_rows = [
        ("校区在哪里？", "星河中心校区位于示例市星河区育才路 88 号 2 层，可在“育才路儿童活动中心”站下车，具体路线以地图导航为准。"),
        ("孩子 4 岁可以学什么？", "可以优先考虑舞蹈启蒙班或音乐启蒙班，两个课程都以游戏和律动为主，重点培养节奏感和身体协调性，建议先预约试听。"),
        ("8 岁零基础可以学编程吗？", "可以。少儿编程基础班面向 8 至 12 岁零基础学员，使用图形化编程工具，课堂电脑由机构提供。"),
        ("一个班有多少名学员？", "不同课程班级容量不同，通常启蒙班不超过 12 人，基础班不超过 14 人，实际开班人数以教务系统为准。"),
        ("试听课收费吗？", "试听是否收费、可预约时间和可试听课程以课程顾问确认的排课结果为准。"),
        ("报名需要准备什么材料？", "登记学员姓名、年龄、意向课程、可上课时间段和家长联系方式即可，不需要提交身份证号码等无关敏感信息。"),
        ("可以插班吗？", "能否插班取决于目标班级是否有容量、课程进度是否匹配，需要由教务确认。"),
        ("课程有效期怎么计算？", "从首次开课或协议约定时间起算，不同套餐有效期不同，例如舞蹈启蒙班 12 节的有效期为 4 个月。"),
        ("剩余课时怎么查？", "指定学员的剩余课时、消课记录和出勤情况需要家长登录后由教务系统查询。"),
        ("课时可以转让给兄弟姐妹吗？", "课程套餐与学员绑定，原则上不能直接转让，特殊情况需要联系教务审核。"),
        ("怎么请假？", "尽量在课程开始前 4 小时通过官方服务渠道提交，填写学员、课程、上课日期和原因。"),
        ("请过假一定能补课吗？", "不一定。需要同课程或相近课程有可预约名额，提交请假不等于补课预约成功。"),
        ("补课没去会怎样？", "未按确认时间参加补课，通常视为放弃本次补课名额，特殊情况由人工审核。"),
        ("学费可以分期吗？", "分期政策以当期活动和订单条款为准，建议联系课程顾问了解当期方案。"),
        ("怎么申请退费？", "提交订单编号和申请原因后由人工审核。未消课且未领取专属材料的可以申请，已消课订单按条款核算，客服不承诺最终金额。"),
        ("报名后有优惠吗？", "优惠、团购、赠课和临时活动价格以订单和当期活动通知为准。"),
        ("孩子可以自己回家吗？", "低龄学员需由家长或监护人接送，不得独自离开校区。委托他人接送时应提前告知教务老师。"),
        ("家长可以进教室看课吗？", "为避免影响课堂秩序，日常课程通常不安排家长进入教室，机构会通过开放日、作品展示或阶段反馈介绍学习情况。"),
        ("可以免费停车吗？", "校区周边停车位有限，是否收费以现场或商场物业规定为准。"),
        ("发票怎么开？", "缴费完成后可在前台登记开票需求，具体开票内容和流程以前台说明为准。"),
        ("对课程或服务不满意怎么办？", "可以联系教务老师说明情况，涉及投诉、争议订单或退费核算的问题会转人工处理并登记工单。"),
    ]
    for question, answer in faq_rows:
        story.append(KeepTogether([P(f"Q：{question}", s["h2"]), P(f"A：{answer}", s["qa"])]))
    story.append(PageBreak())

    # 附录：版权、隐私与使用声明。
    story += [
        P("附录：版权、隐私与使用声明", s["h1"]),
        P("本手册为演示资料，全部课程、价格、教师、地址、活动和图片均为虚构内容，未复制任何第三方网站的整段文案或图片。正式使用前，应由机构管理员逐条确认资质、价格、退费、教师肖像授权、场地安全和数据处理要求。", s["body"]),
        P("学员照片、身份证件、家庭住址和家长联系方式等个人信息不应出现在公开手册中。涉及法律或监管判断时，应由专业人员审核。", s["callout"]),
        P("如有疑问，欢迎在营业时间内到校区咨询或联系前台工作人员。", s["body"]),
    ]

    doc.build(story)
    return OUTPUT_PDF


if __name__ == "__main__":
    print(build_pdf())
