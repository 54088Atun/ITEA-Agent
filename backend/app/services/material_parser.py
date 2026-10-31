"""教学资料文本解析:把上传的目录/大纲文件转成纯文本

支持格式(与前端提示一致):txt / md / docx / xlsx
PDF 需额外依赖,当前不支持,避免引入未验证的重依赖。
"""
from pathlib import Path

from fastapi import HTTPException

SUPPORTED_EXTS = {".txt", ".md", ".docx", ".xlsx", ".xlsm"}


def extract_text(path: Path, filename: str, max_chars: int = 12000) -> str:
    ext = Path(filename).suffix.lower()
    if ext in (".txt", ".md"):
        text = path.read_text(encoding="utf-8", errors="ignore")
    elif ext == ".docx":
        from docx import Document
        doc = Document(str(path))
        text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    elif ext in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        wb = load_workbook(str(path), read_only=True, data_only=True)
        lines = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) for c in row if c is not None]
                if cells:
                    lines.append(" | ".join(cells))
        text = "\n".join(lines)
    else:
        raise HTTPException(
            status_code=400,
            detail="暂不支持该文件格式，请上传 TXT / MD / DOCX / XLSX",
        )

    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="文件内容为空，无法解析")
    return text[:max_chars]
