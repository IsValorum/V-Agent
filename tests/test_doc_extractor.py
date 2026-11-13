import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'agent'), str(ROOT / 'web_mcp')]

import doc_extractor
import pc_mcp
from access_policy import AccessDenied, AccessPolicy


def _build_pdf_bytes(page_texts: list[str]) -> bytes:
    """Construye un PDF multipágina mínimo y válido sin dependencias externas."""
    objects: list[bytes] = []
    # 1: Catalog, 2: Pages, 3: Font Helvetica, 4..: Page/Contents pairs
    num_pages = len(page_texts)
    page_ids = [4 + i * 2 for i in range(num_pages)]
    kids_ref = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [ {kids_ref} ] /Count {num_pages} >>".encode("ascii"))
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, text in enumerate(page_texts):
        cid = 5 + i * 2
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {cid} 0 R >>".encode("ascii")
        )
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin1")
        objects.append(
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for idx, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{idx} 0 obj\n".encode("ascii"))
        out.extend(body)
        out.extend(b"\nendobj\n")
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    return bytes(out)


class DocExtractorTests(unittest.TestCase):
    def test_pdf_extract_and_page_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            pdf_path = Path(folder) / "informe.pdf"
            pdf_path.write_bytes(_build_pdf_bytes(["Primera pagina PDF", "Segunda pagina secreta", "Tercera pagina final"]))
            full = doc_extractor.extract_file(pdf_path, config={"max_pages": 0, "max_chars": 0, "ocr_scanned": False})
            self.assertIn("Primera pagina PDF", full)
            self.assertIn("Segunda pagina secreta", full)
            self.assertIn("Tercera pagina final", full)

            only_two = doc_extractor.extract_file(pdf_path, pages="2", config={"max_pages": 0, "max_chars": 0, "ocr_scanned": False})
            self.assertNotIn("Primera pagina PDF", only_two)
            self.assertIn("Segunda pagina secreta", only_two)

            capped = doc_extractor.extract_file(pdf_path, config={"max_pages": 1, "max_chars": 0, "ocr_scanned": False})
            self.assertIn("Primera pagina PDF", capped)
            self.assertNotIn("Segunda pagina secreta", capped)
            self.assertIn("max_pages=1", capped)

    def test_pdf_ocr_fallback_when_scanned(self):
        with tempfile.TemporaryDirectory() as folder:
            pdf_path = Path(folder) / "escaneado.pdf"
            pdf_path.write_bytes(_build_pdf_bytes([""]))
            with patch.object(doc_extractor, "_ocr_pdf_page", return_value="Texto recuperado con Windows OCR"):
                with_ocr = doc_extractor.extract_file(pdf_path, ocr_scanned=True, max_chars=0)
                self.assertIn("[OCR]\nTexto recuperado con Windows OCR", with_ocr)
                without_ocr = doc_extractor.extract_file(pdf_path, ocr_scanned=False, max_chars=0)
                self.assertIn("(Page has no extractable text)", without_ocr)

    def test_docx_xlsx_pptx_extraction(self):
        import docx
        import openpyxl
        from pptx import Presentation

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            docx_path = root / "nota.docx"
            d = docx.Document()
            d.add_heading("Resumen Ejecutivo", level=1)
            d.add_paragraph("Primer parrafo importante.")
            tbl = d.add_table(rows=2, cols=2)
            tbl.cell(0, 0).text = "Modelo"
            tbl.cell(0, 1).text = "VRAM"
            tbl.cell(1, 0).text = "Gemma 4"
            tbl.cell(1, 1).text = "18 GiB"
            d.save(docx_path)

            res_docx = doc_extractor.extract_file(docx_path, max_chars=0)
            self.assertIn("# Resumen Ejecutivo", res_docx)
            self.assertIn("| Modelo | VRAM |", res_docx)
            self.assertIn("| Gemma 4 | 18 GiB |", res_docx)

            xlsx_path = root / "tabla.xlsx"
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Costes"
            ws.append(["Mes", "Importe"])
            ws.append(["Enero", 1200])
            wb2 = wb.create_sheet("Notas")
            wb2.append(["Detalle", "OK"])
            wb.save(xlsx_path)
            wb.close()

            res_xlsx = doc_extractor.extract_file(xlsx_path, max_chars=0)
            self.assertIn("## Sheet 1: Costes", res_xlsx)
            self.assertIn("| Enero | 1200 |", res_xlsx)
            self.assertIn("## Sheet 2: Notas", res_xlsx)

            pptx_path = root / "deck.pptx"
            prs = Presentation()
            slide = prs.slides.add_slide(prs.slide_layouts[1])
            slide.shapes.title.text = "Plan de Arquitectura"
            slide.placeholders[1].text = "Motor local sin fugas"
            slide.notes_slide.notes_text_frame.text = "Nota del orador"
            prs.save(pptx_path)

            res_pptx = doc_extractor.extract_file(pptx_path, max_chars=0)
            self.assertIn("Plan de Arquitectura", res_pptx)
            self.assertIn("Motor local sin fugas", res_pptx)
            self.assertIn("Nota del orador", res_pptx)

    def test_odt_epub_rtf_and_pagination(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            odt_path = root / "texto.odt"
            with zipfile.ZipFile(odt_path, "w") as zf:
                zf.writestr(
                    "content.xml",
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
                    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
                    '<office:body><office:text><text:h text:outline-level="1">Titulo ODT</text:h>'
                    '<text:p>Contenido LibreOffice.</text:p></office:text></office:body></office:document-content>',
                )
            self.assertIn("# Titulo ODT", doc_extractor.extract_file(odt_path, max_chars=0))
            self.assertIn("Contenido LibreOffice.", doc_extractor.extract_file(odt_path, max_chars=0))

            epub_path = root / "libro.epub"
            with zipfile.ZipFile(epub_path, "w") as zf:
                zf.writestr(
                    "META-INF/container.xml",
                    '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                    '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
                )
                zf.writestr(
                    "OEBPS/content.opf",
                    '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/">'
                    '<metadata><dc:title>Manual EPUB</dc:title></metadata>'
                    '<manifest><item id="c1" href="cap1.xhtml" media-type="application/xhtml+xml"/></manifest>'
                    '<spine><itemref idref="c1"/></spine></package>',
                )
                zf.writestr("OEBPS/cap1.xhtml", "<html><body><h1>Capitulo 1</h1><p>Texto EPUB legible.</p></body></html>")
            epub_text = doc_extractor.extract_file(epub_path, max_chars=0)
            self.assertIn("Manual EPUB", epub_text)
            self.assertIn("Texto EPUB legible.", epub_text)

            rtf_path = root / "carta.rtf"
            rtf_path.write_text(r"{\rtf1\ansi Hola \b mundo\b0\par Segunda linea importante en RTF.}", encoding="ascii")
            chunk1 = doc_extractor.extract_file(rtf_path, max_chars=30, include_metadata=False)
            self.assertIn("[Document truncated:", chunk1)
            full_rtf = doc_extractor.extract_file(rtf_path, max_chars=0, include_metadata=False)
            self.assertIn("Hola mundo", full_rtf)
            self.assertIn("Segunda linea importante en RTF.", full_rtf)

    def test_pc_mcp_doc_read_and_sandbox_and_buscador_remote_pdf(self):
        with tempfile.TemporaryDirectory() as sandbox, tempfile.TemporaryDirectory() as outside:
            policy = AccessPolicy(Path(sandbox))
            in_pdf = Path(sandbox) / "local.pdf"
            out_pdf = Path(outside) / "fuera.pdf"
            payload = _build_pdf_bytes(["Contenido local del sandbox"])
            in_pdf.write_bytes(payload)
            out_pdf.write_bytes(payload)

            with patch.object(doc_extractor, "_ocr_pdf_page", return_value=""):
                out = pc_mcp.call("doc_read", {"path": "local.pdf"}, full_access=False, policy=policy)
            self.assertIn("Contenido local del sandbox", out)

            with self.assertRaises(ValueError) as ctx:
                pc_mcp.call("fs_read", {"path": "local.pdf"}, full_access=False, policy=policy)
            self.assertIn("doc_read", str(ctx.exception))

            with self.assertRaises(AccessDenied):
                pc_mcp.call("doc_read", {"path": str(out_pdf)}, full_access=False, policy=policy)

            import buscador_mcp as web

            class FakeResponse:
                is_redirect = False
                headers = {"Content-Type": "application/pdf"}
                encoding = None

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    pass

                def raise_for_status(self):
                    pass

                def iter_content(self, size):
                    yield payload

            class FakeSession:
                headers = {}

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    pass

                def get(self, *args, **kwargs):
                    return FakeResponse()

            with patch.object(web, "validate_public_url"), patch.object(web.requests, "Session", return_value=FakeSession()):
                visited = json.loads(web.web_visit("https://example.org/informe.pdf"))
            self.assertIn("Contenido local del sandbox", visited["content"])


if __name__ == "__main__":
    unittest.main()
