"""多格式资料解析:文本/代码/Office/PDF/图片的格式校验与抽取"""
import asyncio
from zipfile import ZipFile

import pytest
from fastapi import HTTPException
from openpyxl import Workbook

from app.services.material_parser import (
    extract_text, extract_text_async, safe_filename, validate_filename,
)


def _write(path, content: bytes | str):
    data = content.encode("utf-8") if isinstance(content, str) else content
    path.write_bytes(data)
    return path


def test_text_code_and_csv(tmp_path):
    md = _write(tmp_path / "a.md", "# 第一章\n- 等价类划分")
    assert "等价类划分" in extract_text(md, "a.md")

    code = _write(tmp_path / "demo.py", "def add(a, b):\n    return a + b\n")
    assert "return a + b" in extract_text(code, "demo.py")

    csv_file = _write(tmp_path / "scores.csv", "姓名,分数\n张三,90\n李四,85\n")
    csv_text = extract_text(csv_file, "scores.csv")
    assert "张三 | 90" in csv_text


def test_docx_and_xlsx(tmp_path):
    from docx import Document

    doc = Document()
    doc.add_paragraph("课程大纲第一章")
    docx_path = tmp_path / "outline.docx"
    doc.save(str(docx_path))
    assert "课程大纲第一章" in extract_text(docx_path, "outline.docx")

    wb = Workbook()
    ws = wb.active
    ws.append(["知识点", "权重"])
    ws.append(["边界值", 0.4])
    xlsx_path = tmp_path / "kp.xlsx"
    wb.save(str(xlsx_path))
    xlsx_text = extract_text(xlsx_path, "kp.xlsx")
    assert "边界值 | 0.4" in xlsx_text


def test_pptx_is_parsed_from_ooxml(tmp_path):
    slide = (
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:t>第一页标题</a:t><a:t>第二段要点</a:t></p:sld>'
    )
    path = tmp_path / "deck.pptx"
    with ZipFile(path, "w") as zf:
        zf.writestr("ppt/slides/slide1.xml", slide)
    text = extract_text(path, "deck.pptx")
    assert "第一页标题" in text and "第二段要点" in text


def test_pdf_branch_runs(tmp_path):
    from pypdf import PdfWriter

    path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with path.open("wb") as f:
        writer.write(f)

    with pytest.raises(HTTPException) as exc:
        extract_text(path, "blank.pdf")
    assert exc.value.status_code == 400
    assert "空" in exc.value.detail


def test_image_and_unknown_format_are_rejected(tmp_path):
    image = _write(tmp_path / "q.png", b"\x89PNG\r\n\x1a\n")
    with pytest.raises(HTTPException) as exc:
        extract_text(image, "q.png")
    assert exc.value.status_code == 400
    assert "识图" in exc.value.detail

    with pytest.raises(HTTPException) as async_exc:
        asyncio.run(extract_text_async(image, "q.png"))
    assert async_exc.value.status_code == 400

    exe = _write(tmp_path / "run.exe", b"MZ")
    with pytest.raises(HTTPException) as unknown:
        validate_filename("run.exe")
    assert unknown.value.status_code == 400
    assert "支持" in unknown.value.detail


def test_filename_is_sanitized():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename(r"..\..\evil.txt") == "evil.txt"
    assert validate_filename("Course.PDF") == ".pdf"
