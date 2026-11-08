"""教学资料文本解析:把上传的目录/大纲/课件转成纯文本

支持格式:
- 文本类:txt / md / csv
- 代码类:py / js / ts / java / c / cpp / h / hpp / cs / go / rs / php / rb /
         sql / html / htm / css / vue / json / xml / yml / yaml / sh / bat
- 文档类:docx / pptx / xlsx / xlsm / pdf
- 图片类:png / jpg / jpeg / webp / bmp(需服务端配置识图模型)

PDF 使用 pypdf;PPTX 直接读取 OOXML,避免额外重依赖。
"""
import csv
import io
import re
from pathlib import Path
from zipfile import ZipFile

from fastapi import HTTPException
from xml.etree import ElementTree as ET

TEXT_EXTS = {".txt", ".md", ".csv"}
CODE_EXTS = {
    ".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".hpp", ".cs", ".go",
    ".rs", ".php", ".rb", ".sql", ".html", ".htm", ".css", ".vue", ".json",
    ".xml", ".yml", ".yaml", ".sh", ".bat",
}
DOC_EXTS = {".docx", ".pptx", ".xlsx", ".xlsm", ".pdf"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
SUPPORTED_EXTS = TEXT_EXTS | CODE_EXTS | DOC_EXTS | IMAGE_EXTS

MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}

SUPPORTED_HINT = "PDF / DOCX / PPTX / XLSX / TXT / MD / CSV / 代码文件 / 图片"


def safe_filename(filename: str) -> str:
    """去掉客户端可能携带的路径,防止目录穿越"""
    return Path((filename or "upload").replace("\\", "/")).name


def validate_filename(filename: str) -> str:
    """校验扩展名白名单,返回小写扩展名"""
    ext = Path(filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"暂不支持该文件格式，支持 {SUPPORTED_HINT}",
        )
    return ext


def _read_plain_text(path: Path) -> str:
    """按 UTF-8 → GBK → 忽略错误 的顺序读取纯文本"""
    data = path.read_bytes()
    for encoding in ("utf-8", "gbk"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def _read_csv(path: Path) -> str:
    rows = []
    for row in csv.reader(io.StringIO(_read_plain_text(path))):
        cells = [cell.strip() for cell in row if cell.strip()]
        if cells:
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def _read_docx(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _read_xlsx(path: Path) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(str(path), read_only=True, data_only=True)
    lines = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None]
            if cells:
                lines.append(" | ".join(cells))
    return "\n".join(lines)


def _read_pptx(path: Path) -> str:
    """PPTX 实为 zip,按页读取 OOXML 中的文本节点"""
    ns = "{http://schemas.openxmlformats.org/drawingml/2006/main}t"
    texts = []
    with ZipFile(str(path)) as zf:
        slides = [
            name for name in zf.namelist()
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
        ]
        slides.sort(key=lambda name: int(re.search(r"(\d+)", name).group(1)))
        for name in slides:
            root = ET.fromstring(zf.read(name))
            for node in root.iter(ns):
                if node.text and node.text.strip():
                    texts.append(node.text.strip())
    return "\n".join(texts)


def _read_pdf_pages(path: Path) -> list[tuple[int, str]]:
    """逐页读取 PDF,返回 [(页码, 该页文本)],供页码定位"""
    try:
        from pypdf import PdfReader
    except ImportError:
        raise HTTPException(
            status_code=400,
            detail="服务端未安装 PDF 解析库，请先安装 pypdf 或将 PDF 转为 DOCX/TXT",
        )
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                raise HTTPException(status_code=400, detail="PDF 已加密，无法解析")
        return [
            (index, page.extract_text() or "")
            for index, page in enumerate(reader.pages, start=1)
        ]
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="PDF 解析失败，请确认文件未损坏")


def _read_pdf(path: Path) -> str:
    return "\n".join(text for _, text in _read_pdf_pages(path))


def extract_text(path: Path, filename: str, max_chars: int = 12000) -> str:
    """同步解析文本/代码/Office/PDF;图片请使用 extract_text_async"""
    ext = validate_filename(filename)
    if ext in IMAGE_EXTS:
        raise HTTPException(
            status_code=400,
            detail="图片资料需配置识图模型后再解析，请改用文本或文档格式",
        )
    if ext in TEXT_EXTS:
        text = _read_csv(path) if ext == ".csv" else _read_plain_text(path)
    elif ext in CODE_EXTS:
        text = _read_plain_text(path)
    elif ext == ".docx":
        text = _read_docx(path)
    elif ext == ".pptx":
        text = _read_pptx(path)
    elif ext in (".xlsx", ".xlsm"):
        text = _read_xlsx(path)
    elif ext == ".pdf":
        text = _read_pdf(path)
    else:  # pragma: no cover - validate_filename 已覆盖
        raise HTTPException(status_code=400, detail=f"暂不支持该文件格式，支持 {SUPPORTED_HINT}")

    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="文件内容为空，无法解析")
    return text[:max_chars]


def extract_text_with_pages(
    path: Path, filename: str, max_chars: int = 12000,
) -> tuple[str, list[dict]]:
    """解析文本并返回页码区间:PDF 按真实页码,其余格式统一记为第 1 页"""
    ext = validate_filename(filename)
    if ext != ".pdf":
        text = extract_text(path, filename, max_chars=max_chars)
        return text, [{"page": 1, "start": 0, "end": len(text)}]

    pages = _read_pdf_pages(path)
    parts: list[str] = []
    spans: list[dict] = []
    offset = 0
    for page_no, page_text in pages:
        page_text = page_text.strip()
        if not page_text:
            continue
        if parts:
            offset += 1  # 与 "\n".join 的分隔符对齐
        spans.append({"page": page_no, "start": offset, "end": offset + len(page_text)})
        parts.append(page_text)
        offset += len(page_text)
        if offset >= max_chars:
            break

    text = "\n".join(parts)[:max_chars]
    if not text.strip():
        raise HTTPException(status_code=400, detail="文件内容为空，无法解析")
    spans = [
        {**span, "end": min(span["end"], len(text))}
        for span in spans if span["start"] < len(text)
    ]
    return text, spans


async def extract_text_async(path: Path, filename: str, max_chars: int = 12000) -> str:
    """异步解析入口:图片走识图模型,其余复用同步解析"""
    ext = validate_filename(filename)
    if ext not in IMAGE_EXTS:
        return extract_text(path, filename, max_chars)

    from app.services.vision import describe_image, vision_enabled

    if not vision_enabled():
        raise HTTPException(
            status_code=400,
            detail="图片资料需先配置识图模型（VISION_MODEL / VISION_API_KEY），或改用文档格式",
        )
    try:
        text = await describe_image(path, MIME_BY_EXT.get(ext, "image/png"))
    except Exception:
        raise HTTPException(status_code=400, detail="图片识别失败，请改用文档格式上传")
    if not text or not text.strip():
        raise HTTPException(status_code=400, detail="未能从图片中识别出文字")
    return text.strip()[:max_chars]
