"""Extracción de texto, tablas y metadatos para PDF y documentos de oficina.

Usa librerías Python con licencias permisivas (MIT / BSD / Apache-2.0):
  - PDF: pypdf + pdfplumber (tablas) + pypdfium2/Windows OCR (páginas escaneadas)
  - Word (.docx): python-docx
  - Excel (.xlsx, .xlsm): openpyxl
  - PowerPoint (.pptx): python-pptx
  - OpenDocument (.odt, .ods, .odp) y EPUB (.epub): zipfile + ElementTree + HTMLParser
  - RTF, HTML, XML, CSV/TSV y texto plano: librería estándar (+ BeautifulSoup si está)
"""
from __future__ import annotations

import csv
import html
import io
import json
import os
import pathlib
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser

from mcp_options import options

SUPPORTED_EXTENSIONS = (
    ".pdf", ".docx", ".xlsx", ".xlsm", ".pptx",
    ".odt", ".ods", ".odp", ".epub", ".rtf",
    ".html", ".htm", ".xhtml", ".xml", ".csv", ".tsv",
    ".txt", ".md", ".json",
)

_MIME_TO_EXT = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel.sheet.macroenabled.12": ".xlsm",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.oasis.opendocument.text": ".odt",
    "application/vnd.oasis.opendocument.spreadsheet": ".ods",
    "application/vnd.oasis.opendocument.presentation": ".odp",
    "application/epub+zip": ".epub",
    "application/rtf": ".rtf",
    "text/rtf": ".rtf",
    "text/csv": ".csv",
    "text/tab-separated-values": ".tsv",
    "text/html": ".html",
    "application/xhtml+xml": ".xhtml",
    "application/xml": ".xml",
    "text/xml": ".xml",
}

_OFFICE_EXTS = {
    ".pdf", ".docx", ".xlsx", ".xlsm", ".pptx",
    ".odt", ".ods", ".odp", ".epub", ".rtf",
}

_OCR_SCRIPT = pathlib.Path(__file__).resolve().with_name("ocr.ps1")


def is_document_path(path_or_ext: str) -> bool:
    ext = pathlib.Path(str(path_or_ext or "").strip()).suffix.lower()
    return ext in SUPPORTED_EXTENSIONS


def infer_extension(filename_or_ext: str = "", content_type: str = "") -> str:
    raw = str(filename_or_ext or "").strip().split("?", 1)[0].split("#", 1)[0]
    if raw.startswith(".") and " " not in raw and "/" not in raw and "\\" not in raw:
        ext = raw.lower()
    else:
        ext = pathlib.Path(raw).suffix.lower()
    if ext in SUPPORTED_EXTENSIONS:
        return ext
    mime = str(content_type or "").split(";", 1)[0].strip().lower()
    if mime in _MIME_TO_EXT:
        return _MIME_TO_EXT[mime]
    for prefix, mapped in _MIME_TO_EXT.items():
        if prefix in mime:
            return mapped
    return ext


def _resolve_config(
    config: dict | None = None,
    *,
    mode: str | None = None,
    max_pages: int | None = None,
    max_chars: int | None = None,
    include_tables: bool | None = None,
    ocr_scanned: bool | None = None,
    include_metadata: bool | None = None,
) -> dict:
    base = dict(options("documents"))
    if config:
        base.update(config)
    if mode is not None:
        base["extract_mode"] = str(mode).strip().lower() or "auto"
    if max_pages is not None:
        base["max_pages"] = max(0, int(max_pages))
    if max_chars is not None:
        base["max_chars"] = max(0, int(max_chars))
    if include_tables is not None:
        base["include_tables"] = bool(include_tables)
    if ocr_scanned is not None:
        base["ocr_scanned"] = bool(ocr_scanned)
    if include_metadata is not None:
        base["include_metadata"] = bool(include_metadata)
    if base.get("extract_mode") not in ("auto", "markdown", "text", "tables"):
        base["extract_mode"] = "auto"
    return base


def _parse_page_spec(spec: str | None, total: int, max_pages: int) -> tuple[list[int], bool]:
    """Convierte un rango tipo '1-3,5' en lista ordenada de páginas 1-based."""
    if total <= 0:
        return [], False
    if spec is None or not str(spec).strip():
        if max_pages and max_pages > 0 and total > max_pages:
            return list(range(1, max_pages + 1)), True
        return list(range(1, total + 1)), False
    selected: set[int] = set()
    for part in str(spec).split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            left, right = token.split("-", 1)
            start = max(1, int(left.strip())) if left.strip() else 1
            end = min(total, int(right.strip())) if right.strip() else total
            if start > end:
                start, end = end, start
            selected.update(range(max(1, start), min(total, end) + 1))
        else:
            num = int(token)
            if 1 <= num <= total:
                selected.add(num)
    ordered = sorted(selected)
    truncated = False
    if max_pages and max_pages > 0 and len(ordered) > max_pages:
        ordered = ordered[:max_pages]
        truncated = True
    return ordered, truncated


def _format_markdown_table(rows: list[list[object]]) -> str:
    cleaned = [
        [re.sub(r"\s+", " ", "" if cell is None else str(cell)).strip() for cell in row]
        for row in rows
        if row and any("" if c is None else str(c).strip() for c in row)
    ]
    if not cleaned:
        return ""
    width = max(len(r) for r in cleaned)
    # Trim completely empty trailing columns
    while width > 0 and all(len(r) < width or not r[width - 1] for r in cleaned):
        width -= 1
    if width <= 0:
        return ""
    norm = [
        [(r[i] if i < len(r) else "").replace("|", "\\|") for i in range(width)]
        for r in cleaned
    ]
    lines = [
        "| " + " | ".join(norm[0]) + " |",
        "| " + " | ".join("---" for _ in range(width)) + " |",
    ]
    for row in norm[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _format_plain_table(rows: list[list[object]]) -> str:
    lines = []
    for row in rows:
        vals = [re.sub(r"\s+", " ", "" if c is None else str(c)).strip() for c in row]
        if any(vals):
            lines.append("\t".join(vals).rstrip("\t"))
    return "\n".join(lines)


def _format_table(rows: list[list[object]], mode: str) -> str:
    if mode == "text":
        return _format_plain_table(rows)
    return _format_markdown_table(rows)


def _format_metadata_header(meta: dict[str, object], mode: str) -> str:
    items = [(k, str(v).strip()) for k, v in meta.items() if v is not None and str(v).strip()]
    if not items:
        return ""
    if mode == "text":
        return "\n".join(f"{k}: {v}" for k, v in items)
    return "\n".join(f"- **{k}:** {v}" for k, v in items)


def _clean_text_block(text: str) -> str:
    lines = [line.rstrip() for line in (text or "").replace("\r\n", "\n").replace("\r", "\n").splitlines()]
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return out


def _ocr_pdf_page(source: pathlib.Path | bytes, page_index_0: int) -> str:
    """Renderiza una página PDF a PNG temporal y ejecuta Windows OCR (agent/ocr.ps1)."""
    if not _OCR_SCRIPT.is_file():
        return ""
    try:
        import pypdfium2 as pdfium
    except Exception:
        return ""
    pdf = None
    page = None
    bitmap = None
    tmp_path = None
    try:
        pdf = pdfium.PdfDocument(source)
        page = pdf[page_index_0]
        bitmap = page.render(scale=2.0)
        pil_img = bitmap.to_pil()
        fd, raw_tmp = tempfile.mkstemp(prefix="vagent_ocr_", suffix=".png")
        os.close(fd)
        tmp_path = pathlib.Path(raw_tmp)
        pil_img.save(tmp_path, format="PNG")
        proc = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(_OCR_SCRIPT),
                "-Path",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if proc.returncode == 0:
            return _clean_text_block(proc.stdout)
    except Exception:
        return ""
    finally:
        for obj in (bitmap, page, pdf):
            if obj is not None and hasattr(obj, "close"):
                try:
                    obj.close()
                except Exception:
                    pass
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
    return ""


def _extract_pdf(source: pathlib.Path | bytes, pages: str | None, cfg: dict) -> dict:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("Falta la dependencia 'pypdf' para leer archivos PDF.") from exc

    reader = PdfReader(io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else str(source))
    if reader.is_encrypted:
        try:
            if reader.decrypt("") == 0:
                raise ValueError("Password-protected PDF cannot be read without a decryption key.")
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("Password-protected PDF cannot be read.") from exc

    total_pages = len(reader.pages)
    selected_pages, truncated_pages = _parse_page_spec(pages, total_pages, cfg["max_pages"])
    mode = cfg["extract_mode"]
    want_tables = bool(cfg["include_tables"] or mode == "tables")

    meta: dict[str, object] = {}
    if cfg["include_metadata"]:
        raw_meta = reader.metadata or {}
        title = getattr(raw_meta, "title", None) or raw_meta.get("/Title")
        author = getattr(raw_meta, "author", None) or raw_meta.get("/Author")
        subject = getattr(raw_meta, "subject", None) or raw_meta.get("/Subject")
        meta = {
            "Format": "PDF",
            "Title": title or "",
            "Author": author or "",
            "Subject": subject or "",
            "Total pages": total_pages,
            "Pages read": f"{len(selected_pages)} ({selected_pages[0]}-{selected_pages[-1]})" if selected_pages else "0",
        }
    title = str((reader.metadata or {}).get("/Title") or "").strip()

    plumber_doc = None
    if want_tables or selected_pages:
        try:
            import pdfplumber
            plumber_source = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else str(source)
            plumber_doc = pdfplumber.open(plumber_source)
        except Exception:
            plumber_doc = None

    sections: list[str] = []
    ocr_pages: list[int] = []
    try:
        for pno in selected_pages:
            idx = pno - 1
            header = f"[Page {pno}]" if mode == "text" else f"## Page {pno}"
            tables_md: list[str] = []
            plumber_page = plumber_doc.pages[idx] if plumber_doc and idx < len(plumber_doc.pages) else None
            if want_tables and plumber_page is not None:
                try:
                    for raw_tbl in plumber_page.extract_tables() or []:
                        rendered = _format_table(raw_tbl, mode)
                        if rendered:
                            tables_md.append(rendered)
                except Exception:
                    pass

            if mode == "tables":
                body = "\n\n".join(tables_md) if tables_md else "(No tables detected on this page)"
                sections.append(f"{header}\n{body}")
                continue

            page_text = ""
            try:
                page_text = _clean_text_block(reader.pages[idx].extract_text() or "")
            except Exception:
                page_text = ""
            if len(re.sub(r"\W+", "", page_text)) < 15 and plumber_page is not None:
                try:
                    alt_text = _clean_text_block(plumber_page.extract_text() or "")
                    if len(alt_text) > len(page_text):
                        page_text = alt_text
                except Exception:
                    pass

            if len(re.sub(r"\W+", "", page_text)) < 25 and not tables_md and cfg["ocr_scanned"]:
                ocr_text = _ocr_pdf_page(source, idx)
                if ocr_text:
                    page_text = f"[OCR]\n{ocr_text}"
                    ocr_pages.append(pno)

            parts = [header]
            if page_text:
                parts.append(page_text)
            if tables_md:
                parts.append("\n\n".join(tables_md))
            if len(parts) == 1:
                parts.append("(Page has no extractable text)")
            sections.append("\n\n".join(parts))
    finally:
        if plumber_doc is not None:
            try:
                plumber_doc.close()
            except Exception:
                pass

    if meta and ocr_pages:
        meta["OCR pages"] = ", ".join(str(p) for p in ocr_pages)
    if truncated_pages:
        sections.append(
            f"[Limit max_pages={cfg['max_pages']} applied: read {len(selected_pages)} of {total_pages} pages. "
            f"Pass pages='...' or set max_pages=0 in MCP Settings to read the rest.]"
        )

    body = "\n\n".join(sections)
    head = _format_metadata_header(meta, mode) if cfg["include_metadata"] else ""
    full = f"{head}\n\n{body}".strip() if head else body.strip()
    return {
        "title": title,
        "text": full,
        "format": "pdf",
        "total_pages": total_pages,
        "pages_read": selected_pages,
        "truncated_pages": truncated_pages,
        "metadata": meta,
    }


def _extract_docx(source: pathlib.Path | bytes, cfg: dict) -> dict:
    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError as exc:
        raise RuntimeError("Falta la dependencia 'python-docx' para leer archivos Word (.docx).") from exc

    doc = Document(io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else str(source))
    mode = cfg["extract_mode"]
    want_tables = bool(cfg["include_tables"] or mode == "tables")
    meta: dict[str, object] = {}
    props = getattr(doc, "core_properties", None)
    title = (getattr(props, "title", "") or "").strip() if props else ""
    if cfg["include_metadata"]:
        meta = {
            "Format": "DOCX",
            "Title": title,
            "Author": (getattr(props, "author", "") or "").strip() if props else "",
            "Paragraphs": len(doc.paragraphs),
            "Tables": len(doc.tables),
        }

    blocks: list[str] = []
    for child in doc.element.body:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            if mode == "tables":
                continue
            para = Paragraph(child, doc)
            text = _clean_text_block(para.text)
            if not text:
                continue
            style_name = (getattr(getattr(para, "style", None), "name", "") or "").lower()
            if mode != "text" and "heading" in style_name:
                m = re.search(r"(\d+)", style_name)
                level = min(6, max(1, int(m.group(1)))) if m else 2
                blocks.append(f"{'#' * level} {text}")
            elif mode != "text" and style_name.startswith("list"):
                blocks.append(f"- {text}")
            else:
                blocks.append(text)
        elif tag == "tbl" and want_tables:
            tbl = Table(child, doc)
            rows = [[cell.text for cell in row.cells] for row in tbl.rows]
            rendered = _format_table(rows, mode)
            if rendered:
                blocks.append(rendered)

    body = "\n\n".join(blocks) or "(No extractable text in Word document)"
    head = _format_metadata_header(meta, mode) if cfg["include_metadata"] else ""
    return {
        "title": title,
        "text": f"{head}\n\n{body}".strip() if head else body.strip(),
        "format": "docx",
        "total_pages": None,
        "pages_read": None,
        "truncated_pages": False,
        "metadata": meta,
    }


def _extract_xlsx(source: pathlib.Path | bytes, pages: str | None, cfg: dict) -> dict:
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError("Falta la dependencia 'openpyxl' para leer archivos Excel (.xlsx).") from exc

    wb = openpyxl.load_workbook(
        io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else str(source),
        read_only=True,
        data_only=True,
    )
    try:
        mode = cfg["extract_mode"]
        sheet_names = list(wb.sheetnames)
        selected_indices, truncated_pages = _parse_page_spec(pages, len(sheet_names), cfg["max_pages"])
        meta: dict[str, object] = {}
        if cfg["include_metadata"]:
            meta = {
                "Format": "XLSX",
                "Total sheets": len(sheet_names),
                "Sheets": ", ".join(sheet_names[i - 1] for i in selected_indices),
            }
        sections: list[str] = []
        for idx in selected_indices:
            name = sheet_names[idx - 1]
            ws = wb[name]
            rows = []
            for row in ws.iter_rows(values_only=True):
                if any(v is not None and str(v).strip() for v in row):
                    rows.append(["" if v is None else v for v in row])
            header = f"[Sheet {idx}: {name}]" if mode == "text" else f"## Sheet {idx}: {name}"
            table_str = _format_table(rows, "text" if mode == "text" else "markdown") if rows else "(Empty sheet)"
            sections.append(f"{header}\n{table_str}")
        if truncated_pages:
            sections.append(f"[Limit max_pages={cfg['max_pages']} applied: read {len(selected_indices)} of {len(sheet_names)} sheets.]")
        body = "\n\n".join(sections) or "(Empty Excel workbook)"
        head = _format_metadata_header(meta, mode) if cfg["include_metadata"] else ""
        return {
            "title": "",
            "text": f"{head}\n\n{body}".strip() if head else body.strip(),
            "format": "xlsx",
            "total_pages": len(sheet_names),
            "pages_read": selected_indices,
            "truncated_pages": truncated_pages,
            "metadata": meta,
        }
    finally:
        wb.close()


def _extract_pptx(source: pathlib.Path | bytes, pages: str | None, cfg: dict) -> dict:
    try:
        from pptx import Presentation
    except ImportError as exc:
        raise RuntimeError("Falta la dependencia 'python-pptx' para leer presentaciones (.pptx).") from exc

    prs = Presentation(io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else str(source))
    mode = cfg["extract_mode"]
    want_tables = bool(cfg["include_tables"] or mode == "tables")
    slides = list(prs.slides)
    selected, truncated_pages = _parse_page_spec(pages, len(slides), cfg["max_pages"])

    props = getattr(prs, "core_properties", None)
    title = (getattr(props, "title", "") or "").strip() if props else ""
    meta: dict[str, object] = {}
    if cfg["include_metadata"]:
        meta = {
            "Format": "PPTX",
            "Title": title,
            "Author": (getattr(props, "author", "") or "").strip() if props else "",
            "Total slides": len(slides),
        }

    sections: list[str] = []
    for s_no in selected:
        slide = slides[s_no - 1]
        header = f"[Slide {s_no}]" if mode == "text" else f"## Slide {s_no}"
        parts: list[str] = []
        for shape in slide.shapes:
            if want_tables and getattr(shape, "has_table", False):
                rows = [[cell.text for cell in row.cells] for row in shape.table.rows]
                rendered = _format_table(rows, mode)
                if rendered:
                    parts.append(rendered)
            elif mode != "tables" and getattr(shape, "has_text_frame", False):
                txt = _clean_text_block(shape.text_frame.text)
                if txt:
                    parts.append(txt)
        if mode != "tables" and getattr(slide, "has_notes_slide", False):
            try:
                notes_txt = _clean_text_block(slide.notes_slide.notes_text_frame.text)
                if notes_txt:
                    parts.append(f"Notes:\n{notes_txt}")
            except Exception:
                pass
        body = "\n\n".join(parts) or "(No text or tables)"
        sections.append(f"{header}\n{body}")

    if truncated_pages:
        sections.append(f"[Limit max_pages={cfg['max_pages']} applied: read {len(selected)} of {len(slides)} slides.]")
    body = "\n\n".join(sections) or "(Empty PowerPoint presentation)"
    head = _format_metadata_header(meta, mode) if cfg["include_metadata"] else ""
    return {
        "title": title,
        "text": f"{head}\n\n{body}".strip() if head else body.strip(),
        "format": "pptx",
        "total_pages": len(slides),
        "pages_read": selected,
        "truncated_pages": truncated_pages,
        "metadata": meta,
    }


def _extract_odf(source: pathlib.Path | bytes, ext: str, cfg: dict) -> dict:
    mode = cfg["extract_mode"]
    want_tables = bool(cfg["include_tables"] or mode == "tables")
    stream = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else str(source)
    with zipfile.ZipFile(stream) as zf:
        root = ET.fromstring(zf.read("content.xml"))
        title = ""
        meta: dict[str, object] = {}
        if "meta.xml" in zf.namelist():
            try:
                mroot = ET.fromstring(zf.read("meta.xml"))
                for elem in mroot.iter():
                    local = elem.tag.rsplit("}", 1)[-1]
                    if local == "title" and elem.text:
                        title = elem.text.strip()
                        break
            except Exception:
                pass
        if cfg["include_metadata"]:
            meta = {"Format": ext.lstrip(".").upper(), "Title": title}

    blocks: list[str] = []

    def _walk(node: ET.Element):
        local = node.tag.rsplit("}", 1)[-1]
        if local in ("h", "p"):
            if mode == "tables":
                return
            txt = _clean_text_block("".join(node.itertext()))
            if txt:
                if local == "h" and mode != "text":
                    level = 2
                    for k, v in node.attrib.items():
                        if k.endswith("outline-level") and str(v).isdigit():
                            level = min(6, max(1, int(v)))
                    blocks.append(f"{'#' * level} {txt}")
                else:
                    blocks.append(txt)
            return
        if local == "table" and want_tables:
            rows: list[list[object]] = []
            for row_el in node:
                if row_el.tag.rsplit("}", 1)[-1] != "table-row":
                    continue
                row_vals = []
                for cell_el in row_el:
                    if cell_el.tag.rsplit("}", 1)[-1] == "table-cell":
                        repeat = 1
                        for k, v in cell_el.attrib.items():
                            if k.endswith("number-columns-repeated") and str(v).isdigit():
                                repeat = min(32, max(1, int(v)))
                        val = _clean_text_block("".join(cell_el.itertext()))
                        row_vals.extend([val] * (repeat if val else 1))
                if any(row_vals):
                    rows.append(row_vals)
            rendered = _format_table(rows, mode)
            if rendered:
                if ext == ".ods":
                    tname = next((v for k, v in node.attrib.items() if k.endswith("name")), "")
                    if tname:
                        blocks.append((f"[Sheet: {tname}]\n" if mode == "text" else f"## Sheet: {tname}\n") + rendered)
                        return
                blocks.append(rendered)
            return
        for child in node:
            _walk(child)

    _walk(root)
    body = "\n\n".join(blocks) or "(No extractable OpenDocument content)"
    head = _format_metadata_header(meta, mode) if cfg["include_metadata"] else ""
    return {
        "title": title,
        "text": f"{head}\n\n{body}".strip() if head else body.strip(),
        "format": ext.lstrip("."),
        "total_pages": None,
        "pages_read": None,
        "truncated_pages": False,
        "metadata": meta,
    }


class _SimpleHTMLTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._skip = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        elif tag in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"):
            self._parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("script", "style", "noscript") and self._skip > 0:
            self._skip -= 1
        elif tag in ("p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr"):
            self._parts.append("\n")

    def handle_data(self, data):
        if self._skip == 0 and data:
            self._parts.append(data)

    def text(self) -> str:
        return _clean_text_block(html.unescape("".join(self._parts)))


def _html_to_text(raw_html: str) -> str:
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(raw_html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return _clean_text_block(soup.get_text("\n"))
    except Exception:
        parser = _SimpleHTMLTextParser()
        parser.feed(raw_html)
        parser.close()
        return parser.text()


def _extract_epub(source: pathlib.Path | bytes, pages: str | None, cfg: dict) -> dict:
    mode = cfg["extract_mode"]
    stream = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else str(source)
    chapters: list[str] = []
    title = ""
    with zipfile.ZipFile(stream) as zf:
        names = set(zf.namelist())
        opf_path = None
        if "META-INF/container.xml" in names:
            croot = ET.fromstring(zf.read("META-INF/container.xml"))
            for elem in croot.iter():
                if elem.tag.rsplit("}", 1)[-1] == "rootfile" and elem.attrib.get("full-path"):
                    opf_path = elem.attrib["full-path"]
                    break
        doc_paths: list[str] = []
        if opf_path and opf_path in names:
            opf_dir = pathlib.PurePosixPath(opf_path).parent
            opf_root = ET.fromstring(zf.read(opf_path))
            manifest: dict[str, str] = {}
            for elem in opf_root.iter():
                local = elem.tag.rsplit("}", 1)[-1]
                if local == "title" and elem.text and not title:
                    title = elem.text.strip()
                elif local == "item":
                    iid = elem.attrib.get("id", "")
                    href = elem.attrib.get("href", "")
                    media = elem.attrib.get("media-type", "")
                    if iid and href and ("html" in media or href.lower().endswith((".html", ".xhtml", ".htm"))):
                        resolved = str((opf_dir / href).as_posix()).lstrip("./")
                        manifest[iid] = resolved
                elif local == "itemref":
                    idref = elem.attrib.get("idref", "")
                    if idref in manifest:
                        doc_paths.append(manifest[idref])
        if not doc_paths:
            doc_paths = sorted(n for n in names if n.lower().endswith((".html", ".xhtml", ".htm")))

        selected, truncated_pages = _parse_page_spec(pages, len(doc_paths), cfg["max_pages"])
        for idx in selected:
            entry = doc_paths[idx - 1]
            if entry in names:
                raw = zf.read(entry).decode("utf-8", errors="replace")
                txt = _html_to_text(raw)
                if txt:
                    header = f"[Section {idx}]" if mode == "text" else f"## Section {idx}"
                    chapters.append(f"{header}\n{txt}")

    meta = {"Format": "EPUB", "Title": title, "Total sections": len(doc_paths)} if cfg["include_metadata"] else {}
    if truncated_pages:
        chapters.append(f"[Limit max_pages={cfg['max_pages']} applied: read {len(selected)} of {len(doc_paths)} sections.]")
    body = "\n\n".join(chapters) or "(No readable EPUB content)"
    head = _format_metadata_header(meta, mode) if cfg["include_metadata"] else ""
    return {
        "title": title,
        "text": f"{head}\n\n{body}".strip() if head else body.strip(),
        "format": "epub",
        "total_pages": len(doc_paths),
        "pages_read": selected,
        "truncated_pages": truncated_pages,
        "metadata": meta,
    }


def _extract_rtf(raw_bytes: bytes, cfg: dict) -> dict:
    text = raw_bytes.decode("latin1", errors="ignore")
    destinations = {
        "aftncn", "aftnsep", "aftnsepc", "annotation", "atnauthor", "atndate", "atnicn", "atnid",
        "atnparent", "atnref", "atntime", "atrfend", "atrfstart", "author", "background",
        "bkmkend", "bkmkstart", "buptim", "category", "colorschememapping", "colortbl",
        "company", "creatim", "datafield", "datastore", "defchp", "defpap", "do", "doccomm",
        "docvar", "dptxbxtext", "ebcend", "ebcstart", "factoidname", "falt", "fchars", "ffdeftext",
        "ffentrymcr", "ffexitmcr", "ffformat", "ffhelptext", "ffl", "ffname", "ffstattext",
        "field", "file", "filetbl", "fldinst", "fldrslt", "fldtype", "fname", "fontemb",
        "fontfile", "fonttbl", "footer", "footerf", "footerl", "footerr", "footnote",
        "formfield", "ftncn", "ftnsep", "ftnsepc", "g", "generator", "gridtbl", "header",
        "headerf", "headerl", "headerr", "hl", "htmltag", "info", "keycode", "keywords",
        "latentstyles", "lchars", "levelnumbers", "leveltext", "lfolevel", "linkval", "list",
        "listlevel", "listname", "listoverride", "listoverridetable", "listpicture", "liststylename",
        "listtable", "listtext", "lsdlockedexcept", "macc", "maccPr", "mailmerge", "maln",
        "malnScr", "manager", "margPr", "mbar", "mbarPr", "mbaseJc", "mbegChr", "mborderBox",
        "mborderBoxPr", "mbox", "mboxPr", "mchr", "mcount", "mctrlPr", "md", "mdeg",
        "mdegHide", "mden", "mdiff", "mdPr", "me", "mendChr", "meqArr", "meqArrPr", "mf",
        "mfName", "mfPr", "mfunc", "mfuncPr", "mgroupChr", "mgroupChrPr", "mgrow", "mhideBot",
        "mhideLeft", "mhideRight", "mhideTop", "mhtmltag", "mlim", "mlimloc", "mlimlow",
        "mlimlowPr", "mlimupp", "mlimuppPr", "mm", "mmaddfieldname", "mmath", "mmathPict",
        "mmathPr", "mmaxdist", "mmc", "mmcJc", "mmconnectstr", "mmconnectstrdata", "mmcPr",
        "mmcs", "mmdatasource", "mmheadersource", "mmmailsubject", "mmodso", "mmodsofilter",
        "mmodsofldmpdata", "mmodsomappedname", "mmodsoname", "mmodsorecipdata", "mmodsosort",
        "mmodsosrc", "mmodsotable", "mmodsoudl", "mmodsoudldata", "mmodsouniquetag",
        "mmPr", "mmquery", "mmr", "mnary", "mnaryPr", "mnoBreak", "mnum", "mobjDist", "moMath",
        "moMathPara", "moMathParaPr", "mopEmu", "mphant", "mphantPr", "mplcHide", "mpos",
        "mr", "mrad", "mradPr", "mrPr", "msepChr", "mshow", "mshp", "msPre", "msPrePr",
        "msSub", "msSubPr", "msSubSup", "msSubSupPr", "msSup", "msSupPr", "mstrikeBLTR",
        "mstrikeH", "mstrikeTLBR", "mstrikeV", "msub", "msubHide", "msup", "msupHide",
        "mtransp", "mtype", "mvertJc", "mvfmf", "mvfml", "mvtof", "mvtol", "mzeroAsc",
        "mzeroDesc", "mzeroWid", "nesttableprops", "nextfile", "nonesttables", "objalias",
        "objclass", "objdata", "object", "objname", "objsect", "objtime", "oldcprops",
        "oldpprops", "oldsprops", "oldtprops", "oleclsid", "operator", "panose", "password",
        "passwordhash", "pgp", "pgptbl", "picprop", "pict", "pn", "pnseclvl", "pntext",
        "pntxta", "pntxtb", "printim", "private", "propname", "protend", "protstart",
        "protusertbl", "pxe", "result", "revtbl", "revtim", "rsidtbl", "rxe", "shp",
        "shpgrp", "shpinst", "shppict", "shprslt", "shptxt", "sn", "sp", "staticval",
        "stylesheet", "subject", "sv", "svb", "tc", "template", "themedata", "title",
        "txe", "ud", "upr", "userprops", "wgrffmtfilter", "windowcaption", "writereservation",
        "writereservhash", "xe", "xform", "xmlattrname", "xmlattrvalue", "xmlclose", "xmlname",
        "xmlnstbl", "xmlopen",
    }
    special = {"par": "\n", "line": "\n", "tab": "\t", "emdash": "—", "endash": "–", "lquote": "‘", "rquote": "’", "ldblquote": "“", "rdblquote": "”", "bullet": "•", "~": " ", "_": "-"}
    pattern = re.compile(r"\\([a-z]{1,32})(-?\d+)?[ ]?|\\'([0-9a-fA-F]{2})|\\([^a-z])|([{}])|[\r\n]+|(.)", re.S)
    stack: list[tuple[int, bool]] = []
    ignorable = False
    ucskip = 1
    curskip = 0
    out: list[str] = []
    for match in pattern.finditer(text):
        word, arg, hexch, tchar, brace, char = match.groups()
        if brace:
            curskip = 0
            if brace == "{":
                stack.append((ucskip, ignorable))
            elif stack:
                ucskip, ignorable = stack.pop()
        elif tchar:
            curskip = 0
            if tchar in special and not ignorable:
                out.append(special[tchar])
            elif tchar == "*":
                ignorable = True
            elif tchar in ("\\", "{", "}") and not ignorable:
                out.append(tchar)
        elif word:
            curskip = 0
            if word in destinations:
                ignorable = True
            elif ignorable:
                pass
            elif word in special:
                out.append(special[word])
            elif word == "uc":
                ucskip = max(0, int(arg)) if arg else 1
            elif word == "u":
                code = int(arg)
                if code < 0:
                    code += 0x10000
                out.append(chr(code))
                curskip = ucskip
        elif hexch:
            if curskip > 0:
                curskip -= 1
            elif not ignorable:
                out.append(bytes.fromhex(hexch).decode("cp1252", errors="replace"))
        elif char:
            if curskip > 0:
                curskip -= 1
            elif not ignorable:
                out.append(char)

    body = _clean_text_block("".join(out)) or "(No extractable RTF text)"
    meta = {"Format": "RTF"} if cfg["include_metadata"] else {}
    head = _format_metadata_header(meta, cfg["extract_mode"]) if cfg["include_metadata"] else ""
    return {
        "title": "",
        "text": f"{head}\n\n{body}".strip() if head else body,
        "format": "rtf",
        "total_pages": None,
        "pages_read": None,
        "truncated_pages": False,
        "metadata": meta,
    }


def _extract_markup_or_text(raw_bytes: bytes, ext: str, cfg: dict) -> dict:
    text = raw_bytes.decode("utf-8-sig", errors="replace")
    mode = cfg["extract_mode"]
    if ext in (".html", ".htm", ".xhtml"):
        title = ""
        m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
        if m:
            title = html.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
        body = _html_to_text(text)
        return {"title": title, "text": body, "format": ext.lstrip("."), "total_pages": None, "pages_read": None, "truncated_pages": False, "metadata": {}}
    if ext in (".csv", ".tsv"):
        delimiter = "\t" if ext == ".tsv" else ","
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
        rendered = _format_table(rows, "text" if mode == "text" else "markdown") or _clean_text_block(text)
        return {"title": "", "text": rendered, "format": ext.lstrip("."), "total_pages": None, "pages_read": None, "truncated_pages": False, "metadata": {}}
    if ext == ".xml":
        try:
            root = ET.fromstring(text)
            lines = [t.strip() for t in root.itertext() if t and t.strip()]
            return {"title": "", "text": "\n".join(lines), "format": "xml", "total_pages": None, "pages_read": None, "truncated_pages": False, "metadata": {}}
        except Exception:
            pass
    if ext == ".json":
        try:
            parsed = json.loads(text)
            return {"title": "", "text": json.dumps(parsed, ensure_ascii=False, indent=2), "format": "json", "total_pages": None, "pages_read": None, "truncated_pages": False, "metadata": {}}
        except Exception:
            pass
    return {"title": "", "text": _clean_text_block(text), "format": ext.lstrip(".") or "txt", "total_pages": None, "pages_read": None, "truncated_pages": False, "metadata": {}}


def extract_bytes(
    data: bytes,
    filename_or_ext: str = "",
    content_type: str = "",
    *,
    pages: str | None = None,
    mode: str | None = None,
    max_pages: int | None = None,
    include_tables: bool | None = None,
    ocr_scanned: bool | None = None,
    include_metadata: bool | None = None,
    config: dict | None = None,
) -> dict:
    ext = infer_extension(filename_or_ext, content_type)
    cfg = _resolve_config(
        config,
        mode=mode,
        max_pages=max_pages,
        include_tables=include_tables,
        ocr_scanned=ocr_scanned,
        include_metadata=include_metadata,
    )
    if ext == ".pdf":
        return _extract_pdf(bytes(data), pages, cfg)
    if ext == ".docx":
        return _extract_docx(bytes(data), cfg)
    if ext in (".xlsx", ".xlsm"):
        return _extract_xlsx(bytes(data), pages, cfg)
    if ext == ".pptx":
        return _extract_pptx(bytes(data), pages, cfg)
    if ext in (".odt", ".ods", ".odp"):
        return _extract_odf(bytes(data), ext, cfg)
    if ext == ".epub":
        return _extract_epub(bytes(data), pages, cfg)
    if ext == ".rtf":
        return _extract_rtf(bytes(data), cfg)
    return _extract_markup_or_text(bytes(data), ext, cfg)


def extract_file(
    path: str | pathlib.Path,
    *,
    pages: str | None = None,
    mode: str | None = None,
    offset: int = 0,
    max_chars: int | None = None,
    max_pages: int | None = None,
    include_tables: bool | None = None,
    ocr_scanned: bool | None = None,
    include_metadata: bool | None = None,
    config: dict | None = None,
) -> str:
    file_path = pathlib.Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if file_path.is_dir():
        raise ValueError(f"{file_path} is a directory, not a document.")
    ext = file_path.suffix.lower()
    if ext and ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported format '{ext}' in doc_read. Supported: {', '.join(SUPPORTED_EXTENSIONS)}"
        )

    cfg = _resolve_config(
        config,
        mode=mode,
        max_pages=max_pages,
        max_chars=max_chars,
        include_tables=include_tables,
        ocr_scanned=ocr_scanned,
        include_metadata=include_metadata,
    )
    offset_i = max(0, int(offset or 0))
    if offset_i < 0:
        raise ValueError("offset must be >= 0.")

    if ext == ".pdf":
        extracted = _extract_pdf(file_path, pages, cfg)
    elif ext == ".docx":
        extracted = _extract_docx(file_path, cfg)
    elif ext in (".xlsx", ".xlsm"):
        extracted = _extract_xlsx(file_path, pages, cfg)
    elif ext == ".pptx":
        extracted = _extract_pptx(file_path, pages, cfg)
    elif ext in (".odt", ".ods", ".odp"):
        extracted = _extract_odf(file_path, ext, cfg)
    elif ext == ".epub":
        extracted = _extract_epub(file_path, pages, cfg)
    else:
        raw = file_path.read_bytes()
        extracted = extract_bytes(
            raw,
            file_path.name,
            pages=pages,
            config=cfg,
        )

    full_text = extracted["text"]
    limit = int(cfg["max_chars"])
    if limit <= 0:
        return full_text[offset_i:] if offset_i < len(full_text) else ""
    chunk = full_text[offset_i:offset_i + limit]
    next_off = offset_i + len(chunk)
    if next_off < len(full_text):
        chunk += (
            f"\n\n[Document truncated: {len(full_text)} total characters. "
            f"Continue with pc__doc_read(path={str(file_path)!r}, offset={next_off}, max_chars={limit})]"
        )
    return chunk
