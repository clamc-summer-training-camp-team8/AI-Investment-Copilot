from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.ingest.parsers import text


def test_rapidocr_engine_is_reused_within_worker_thread() -> None:
    text._OCR_LOCAL.engine = None
    engine = MagicMock()

    with patch("rapidocr.RapidOCR", return_value=engine) as factory:
        first = text._rapidocr_engine()
        second = text._rapidocr_engine()

    assert first is engine
    assert second is engine
    factory.assert_called_once_with(
        params={
            "EngineConfig.onnxruntime.intra_op_num_threads": 4,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            "Global.log_level": "warning",
        }
    )
    text._OCR_LOCAL.engine = None


def test_ocr_page_uses_poppler_fallback_and_releases_image() -> None:
    image = MagicMock()
    engine = MagicMock(return_value=SimpleNamespace(txts=["正文"], scores=[0.98]))

    with (
        patch("pypdfium2.PdfDocument", side_effect=RuntimeError("bad xref")),
        patch.object(text, "_render_pdf_page_with_poppler", return_value=image) as fallback,
        patch.object(text, "_rapidocr_engine", return_value=engine),
    ):
        result = text._ocr_pdf_page(Path("broken.pdf"), 2)

    assert result == [("正文", Decimal("0.98"))]
    fallback.assert_called_once_with(Path("broken.pdf"), 2)
    engine.assert_called_once_with(image)
    image.close.assert_called_once_with()


def test_resource_cleanup_continues_when_one_close_fails() -> None:
    broken = MagicMock()
    broken.close.side_effect = RuntimeError("already closed")
    healthy = MagicMock()

    text._close_pdf_resources(broken, healthy)

    broken.close.assert_called_once_with()
    healthy.close.assert_called_once_with()
