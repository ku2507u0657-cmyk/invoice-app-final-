"""
utils/qr.py — UPI QR code generation for invoice payments.

Generates a QR code image (PNG bytes) encoding a UPI deep-link
that payment apps (GPay, PhonePe, Paytm, BHIM) can scan.

UPI deep-link format:
    upi://pay?pa=<UPI_ID>&pn=<PAYEE_NAME>&am=<AMOUNT>&cu=INR&tn=<NOTE>

Usage
-----
    from utils.qr import build_upi_qr_bytes
    png_bytes = build_upi_qr_bytes("yourname@upi", "Acme Ltd", 1180.00, "INV-0001")
"""

import io
import logging
from urllib.parse import urlencode, quote

logger = logging.getLogger(__name__)


def build_upi_qr_bytes(upi_id: str, payee_name: str,
                        amount: float, note: str = "") -> bytes:
    """
    Generate a UPI payment QR code and return raw PNG bytes.

    Parameters
    ----------
    upi_id      : UPI VPA, e.g. 'yourname@okicici'
    payee_name  : Display name shown in payment app
    amount      : Amount in INR (float, 2 d.p.)
    note        : Short payment note shown to payer (optional)

    Returns
    -------
    bytes : PNG image data, or empty bytes if qrcode is not installed
    """
    try:
        import qrcode
        from qrcode.image.pure import PyPNGImage

        params = {
            "pa": upi_id,
            "pn": payee_name,
            "am": f"{amount:.2f}",
            "cu": "INR",
        }
        if note:
            params["tn"] = note[:50]   # UPI spec: max 50 chars

        upi_url = "upi://pay?" + urlencode(params, quote_via=quote)

        qr = qrcode.QRCode(
            version        = 3,
            error_correction = qrcode.constants.ERROR_CORRECT_M,
            box_size       = 6,
            border         = 2,
        )
        qr.add_data(upi_url)
        qr.make(fit=True)

        # Use PIL image for better quality
        try:
            from PIL import Image
            img = qr.make_image(fill_color="black", back_color="white")
        except ImportError:
            img = qr.make_image(image_factory=PyPNGImage)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    except ImportError:
        logger.warning("qrcode or Pillow not installed — UPI QR disabled.")
        return b""
    except Exception as exc:
        logger.error("UPI QR generation failed: %s", exc)
        return b""


def build_upi_qr_for_invoice(invoice, app) -> bytes:
    """
    Convenience wrapper — reads UPI config from app and generates QR
    for the given invoice's total amount.
    """
    upi_id     = app.config.get("UPI_ID", "")
    payee_name = app.config.get("UPI_PAYEE_NAME",
                                app.config.get("COMPANY_NAME", "InvoiceFlow"))

    if not upi_id:
        logger.info("UPI_ID not configured — skipping QR code.")
        return b""

    return build_upi_qr_bytes(
        upi_id     = upi_id,
        payee_name = payee_name,
        amount     = float(invoice.total),
        note       = invoice.invoice_number,
    )
