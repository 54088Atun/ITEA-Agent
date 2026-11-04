"""班级学生批量导入文件解析:支持 CSV / XLSX

列名兼容: email/邮箱、student_id/id/user_id/用户ID/学号(取其一即可)
"""
import csv
import io

from openpyxl import load_workbook

MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_IMPORT_ROWS = 500

EMAIL_KEYS = {"email", "e-mail", "邮箱", "电子邮箱"}
ID_KEYS = {"student_id", "id", "user_id", "用户id", "用户ID", "学号"}


def _norm(value) -> str:
    return str(value or "").strip()


def _pick_key(headers, candidates):
    lower = {_norm(h).lower(): h for h in headers}
    for key in candidates:
        if key.lower() in lower:
            return lower[key.lower()]
    return None


def parse_student_rows(content: bytes, filename: str) -> list[dict]:
    if len(content) > MAX_IMPORT_BYTES:
        raise ValueError("文件超过 2MB 限制")
    name = (filename or "").lower()
    if name.endswith(".csv"):
        rows = _parse_csv(content)
    elif name.endswith(".xlsx"):
        rows = _parse_xlsx(content)
    elif name.endswith(".xls"):
        raise ValueError("暂不支持 .xls，请另存为 .xlsx 或 CSV")
    else:
        raise ValueError("仅支持 CSV 或 XLSX 文件")
    if len(rows) > MAX_IMPORT_ROWS:
        raise ValueError(f"单次最多导入 {MAX_IMPORT_ROWS} 行")
    return rows


def _rows_from_matrix(matrix):
    matrix = [row for row in matrix if any(_norm(cell) for cell in row)]
    if not matrix:
        return []
    headers = matrix[0]
    email_key = _pick_key(headers, EMAIL_KEYS)
    id_key = _pick_key(headers, ID_KEYS)
    if not email_key and not id_key:
        raise ValueError("缺少 email 或 student_id 列")
    index = {header: i for i, header in enumerate(headers)}
    result = []
    for offset, row in enumerate(matrix[1:], start=2):
        def cell(key):
            if not key:
                return ""
            i = index.get(key)
            return _norm(row[i]) if i is not None and i < len(row) else ""

        result.append({
            "row": offset,
            "email": cell(email_key),
            "student_id": cell(id_key),
        })
    return result


def _parse_csv(content: bytes) -> list[dict]:
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    return _rows_from_matrix([list(row) for row in reader])


def _parse_xlsx(content: bytes) -> list[dict]:
    workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        sheet = workbook.active
        matrix = [list(row) for row in sheet.iter_rows(values_only=True)]
    finally:
        workbook.close()
    return _rows_from_matrix(matrix)
