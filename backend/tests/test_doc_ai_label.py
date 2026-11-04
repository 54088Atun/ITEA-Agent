"""AG-08 统一 AI 标识:三类导出文件都必须带 [AI 辅助参考]

覆盖教案 docx、预习单 docx、学情报表 xlsx(含两个 sheet)。
"""
import importlib
from pathlib import Path

from openpyxl import load_workbook

dg = importlib.import_module("app.agent.tools.doc_generator")


def _output_path(tmp_path, result) -> Path:
    assert not result.get("error"), result
    return Path(tmp_path) / result["file_name"]


def test_lesson_plan_docx_has_ai_tag(tmp_path, monkeypatch):
    monkeypatch.setattr(dg, "OUTPUT_DIR", str(tmp_path))
    result = dg.doc_generator("lesson_plan", {
        "course_name": "软件测试",
        "sections": {"教学目标": "掌握等价类"},
    })
    from docx import Document

    text = "\n".join(p.text for p in Document(_output_path(tmp_path, result)).paragraphs)
    assert "[AI 辅助参考" in text


def test_preview_sheet_docx_has_ai_tag(tmp_path, monkeypatch):
    monkeypatch.setattr(dg, "OUTPUT_DIR", str(tmp_path))
    result = dg.doc_generator("preview_sheet", {
        "topic": "等价类划分",
        "goals": ["理解有效/无效等价类"],
    })
    from docx import Document

    text = "\n".join(p.text for p in Document(_output_path(tmp_path, result)).paragraphs)
    assert "[AI 辅助参考" in text


def test_class_report_xlsx_has_ai_tag_on_every_sheet(tmp_path, monkeypatch):
    monkeypatch.setattr(dg, "OUTPUT_DIR", str(tmp_path))
    result = dg.doc_generator("report", {
        "rows": [{
            "student_name": "小明", "knowledge_point": "等价类",
            "mastery_level": 0.8, "wrong_count": 1, "pending_reviews": 2,
        }],
        "weak_points": [{"point": "边界值", "avg_mastery": 0.4, "wrong_count": 3}],
    })
    workbook = load_workbook(_output_path(tmp_path, result))
    assert workbook.sheetnames == ["学情汇总", "薄弱知识点TOP10"]
    for sheet in workbook.worksheets:
        first = sheet.cell(row=1, column=1).value
        assert first and "[AI 辅助参考" in str(first)
