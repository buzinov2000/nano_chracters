import io
import math

from PIL import Image, ImageDraw, ImageFont


CELL_WIDTH = 512
PADDING = 8
NUMBER_FONT_SIZE = 48


def make_grid(images: list[bytes], columns: int = 2) -> bytes:
    """Собирает сетку превью с номерами, сохраняя пропорции картинок."""
    count = len(images)
    rows = math.ceil(count / columns)

    # Определяем пропорции по первой картинке
    first = Image.open(io.BytesIO(images[0]))
    aspect = first.height / first.width
    cell_w = CELL_WIDTH
    cell_h = int(CELL_WIDTH * aspect)

    grid_w = columns * cell_w + (columns + 1) * PADDING
    grid_h = rows * cell_h + (rows + 1) * PADDING

    canvas = Image.new("RGB", (grid_w, grid_h), (245, 245, 245))
    draw = ImageDraw.Draw(canvas)

    try:
        font = ImageFont.truetype("arial.ttf", NUMBER_FONT_SIZE)
    except OSError:
        font = ImageFont.load_default(size=NUMBER_FONT_SIZE)

    for idx, img_bytes in enumerate(images):
        img = Image.open(io.BytesIO(img_bytes))
        img = img.resize((cell_w, cell_h), Image.LANCZOS)

        row, col = divmod(idx, columns)
        x = PADDING + col * (cell_w + PADDING)
        y = PADDING + row * (cell_h + PADDING)
        canvas.paste(img, (x, y))

        # Номер с обводкой
        label = str(idx + 1)
        lx, ly = x + 12, y + 6
        for dx in (-2, 0, 2):
            for dy in (-2, 0, 2):
                draw.text((lx + dx, ly + dy), label, fill="black", font=font)
        draw.text((lx, ly), label, fill="white", font=font)

    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=85)
    return buf.getvalue()
