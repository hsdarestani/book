"""Private, bounded file previews. No document leaves the booking server."""
import io
import math
import mimetypes
import threading
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageOps

PDF_LOCK = threading.RLock()  # PDFium calls must not overlap within a process.


def file_kind(record):
    extension = Path(record.original_name or record.stored_name).suffix.lower()
    mime = (record.mime_type or '').split(';')[0].lower()
    if mime == 'application/pdf' or extension == '.pdf':
        return 'pdf'
    if mime.startswith('image/') or extension in {'.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif'}:
        return 'image'
    if extension in {'.txt', '.csv'}:
        return 'text'
    return 'document'


def content_type(record, path):
    with path.open('rb') as stream:
        signature = stream.read(16)
    for magic, mime in ((b'%PDF-', 'application/pdf'), (b'\x89PNG\r\n\x1a\n', 'image/png'),
                        (b'\xff\xd8\xff', 'image/jpeg')):
        if signature.startswith(magic):
            return mime
    return mimetypes.guess_type(record.original_name or path.name)[0] or record.mime_type or 'application/octet-stream'


def pdf_page_count(path):
    import pypdfium2 as pdfium
    with PDF_LOCK:
        with pdfium.PdfDocument(str(path)) as document:
            return len(document)


def preview_bytes(path, kind, page=1, full=False):
    stat = path.stat()
    # A small process-local cache avoids repeated PDF rendering and never creates
    # extra patient files on disk or sends bytes to an external cache service.
    return _render(str(path), stat.st_mtime_ns, stat.st_size, kind, page, full)


@lru_cache(maxsize=48)
def _render(filename, modified, length, kind, page, full):
    width, height = (1400, 2200) if full else (520, 620)
    if kind == 'pdf':
        import pypdfium2 as pdfium
        with PDF_LOCK:
            with pdfium.PdfDocument(filename) as document:
                if not 1 <= page <= len(document):
                    raise ValueError('Invalid page')
                pdf_page = document[page - 1]
                try:
                    w, h = pdf_page.get_size()
                    if w <= 0 or h <= 0 or not math.isfinite(w + h):
                        raise ValueError('Invalid page dimensions')
                    scale = min(width / w, height / h)
                    bitmap = pdf_page.render(scale=scale)
                    try:
                        image = bitmap.to_pil().copy()
                    finally:
                        bitmap.close()
                finally:
                    pdf_page.close()
    elif kind == 'image':
        with Image.open(filename) as source:
            image = ImageOps.exif_transpose(source)
            image.thumbnail((width, height))
            image = image.copy()
    elif kind == 'text':
        import textwrap
        from PIL import ImageDraw, ImageFont
        image = Image.new('RGB', (width, height), 'white')
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=16 if not full else 24)
        lines = []
        for paragraph in text_excerpt(Path(filename)).splitlines():
            lines.extend(textwrap.wrap(paragraph.expandtabs(3), width=55 if not full else 90) or [''])
            if len(lines) > 24:
                break
        draw.multiline_text((20, 24), '\n'.join(lines[:24]), fill='#292c2a', font=font, spacing=6)
    else:
        raise ValueError('No image preview')
    try:
        if image.mode in {'RGBA', 'LA'} or 'transparency' in image.info:
            rgba = image.convert('RGBA')
            background = Image.new('RGB', rgba.size, 'white')
            background.paste(rgba, mask=rgba.getchannel('A'))
            rgba.close()
            image.close()
            image = background
        elif image.mode != 'RGB':
            converted = image.convert('RGB')
            image.close()
            image = converted
        output = io.BytesIO()
        image.save(output, 'JPEG', quality=85 if full else 76)
        return output.getvalue()
    finally:
        image.close()


def text_excerpt(path):
    with path.open('rb') as stream:
        return stream.read(80_000).decode('utf-8-sig', errors='replace')


def fallback_preview():
    """A neutral local placeholder for unsupported/corrupt formats."""
    from PIL import ImageDraw
    image = Image.new('RGB', (520, 280), '#f4f3ef')
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((215, 60, 305, 190), radius=8, outline='#9a8a69', width=3)
    for y in (100, 120, 140, 160):
        draw.line((235, y, 285, y), fill='#c5bdac', width=3)
    output = io.BytesIO()
    image.save(output, 'JPEG', quality=76)
    image.close()
    return output.getvalue()
