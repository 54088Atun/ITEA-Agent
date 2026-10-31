"""doc_generator:文档生成(python-docx / openpyxl)

实现要点:
- python-docx 生成教案/预习单
- openpyxl 生成学情报表
- 生成文件存 static 目录返回下载链接
"""
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# 生成文件存放目录
OUTPUT_DIR = os.path.join("static", "generated")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def _generate_lesson_plan(data: dict) -> str:
    """生成教案 docx"""
    from docx import Document

    doc = Document()
    doc.add_heading(f"教案:{data.get('course_name', '未命名课程')}", level=1)
    doc.add_paragraph(f"生成时间:{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    doc.add_paragraph("[AI 辅助参考,请教师审核修改]")

    sections = data.get("sections", {})
    for title, content in sections.items():
        doc.add_heading(title, level=2)
        if isinstance(content, list):
            for item in content:
                doc.add_paragraph(item, style="List Bullet")
        else:
            doc.add_paragraph(str(content))

    filename = f"lesson_plan_{datetime.now().strftime('%Y%m%d%H%M%S')}.docx"
    filepath = os.path.join(OUTPUT_DIR, filename)
    doc.save(filepath)
    return filename


def _generate_preview_sheet(data: dict) -> str:
    """生成预习单 docx"""
    from docx import Document

    doc = Document()
    doc.add_heading(f"预习单:{data.get('topic', '未命名主题')}", level=1)
    doc.add_paragraph("[AI 辅助参考,请师生审核]")

    doc.add_heading("预习目标", level=2)
    for goal in data.get("goals", ["理解基本概念"]):
        doc.add_paragraph(goal, style="List Bullet")

    doc.add_heading("预习问题", level=2)
    for q in data.get("questions", []):
        doc.add_paragraph(q, style="List Number")

    doc.add_heading("参考资料", level=2)
    for ref in data.get("references", ["教材相关章节"]):
        doc.add_paragraph(ref, style="List Bullet")

    filename = f"preview_sheet_{datetime.now().strftime('%Y%m%d%H%M%S')}.docx"
    filepath = os.path.join(OUTPUT_DIR, filename)
    doc.save(filepath)
    return filename


def _generate_report(data: dict) -> str:
    """生成学情报表 xlsx"""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "学情汇总"

    # 表头
    headers = ["学生", "知识点", "掌握度", "错题数", "待复习"]
    ws.append(headers)
    for col in range(1, len(headers) + 1):
        ws.cell(row=1, column=col).font = ws.cell(row=1, column=col).font.copy(bold=True)

    # 数据行
    for row_data in data.get("rows", []):
        ws.append([
            row_data.get("student_name", ""),
            row_data.get("knowledge_point", ""),
            row_data.get("mastery_level", 0),
            row_data.get("wrong_count", 0),
            row_data.get("pending_reviews", 0),
        ])

    # 薄弱知识点汇总 sheet
    ws2 = wb.create_sheet("薄弱知识点TOP10")
    ws2.append(["排名", "知识点", "平均掌握度", "错题人次"])
    for i, wp in enumerate(data.get("weak_points", [])[:10], 1):
        ws2.append([i, wp.get("point", ""), wp.get("avg_mastery", 0), wp.get("wrong_count", 0)])

    filename = f"class_report_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"
    filepath = os.path.join(OUTPUT_DIR, filename)
    wb.save(filepath)
    return filename


def doc_generator(
    doc_type: str,
    data: dict,
) -> dict:
    """文档生成工具

    Args:
        doc_type: 文档类型(lesson_plan/preview_sheet/report)
        data: 文档内容数据

    Returns:
        {"file_url": "/static/generated/xxx.docx", "file_name": "xxx.docx"}
    """
    generators = {
        "lesson_plan": _generate_lesson_plan,
        "preview_sheet": _generate_preview_sheet,
        "report": _generate_report,
    }
    gen = generators.get(doc_type)
    if not gen:
        return {"file_url": "", "file_name": "", "error": f"不支持的文档类型: {doc_type}"}

    try:
        filename = gen(data)
        logger.info("文档生成成功: %s (%s)", filename, doc_type)
        return {
            "file_url": f"/static/generated/{filename}",
            "file_name": filename,
        }
    except Exception as e:
        logger.error("文档生成失败(%s): %s", doc_type, e)
        return {"file_url": "", "file_name": "", "error": str(e)}