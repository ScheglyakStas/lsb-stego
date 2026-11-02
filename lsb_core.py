"""Ядро LSB-стеганографии для BMP-изображений (без зависимости от GUI).

Порядок встраивания битов: пиксели обходятся построчно с заданным шагом,
внутри пикселя — выбранные цветовые компоненты в порядке R, G, B,
внутри компоненты — выбранные битовые плоскости от младшей к старшей.

Формат полезной нагрузки: 32-битная длина сообщения в байтах (big-endian),
затем сами байты сообщения.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageOps

HEADER_BITS = 32
MAX_PLANE = 4

CHANNEL_NAMES = ("Красный (R)", "Зелёный (G)", "Синий (B)")

# (число пропускаемых пикселей, подпись)
INTERVALS = (
    (0, "В каждый пиксель"),
    (1, "Через один пиксель"),
    (2, "Через два пикселя"),
    (3, "Через три пикселя"),
    (4, "Через четыре пикселя"),
)


class StegoError(Exception):
    pass


IMAGE_EXTENSIONS = (
    "bmp", "dib", "png", "jpg", "jpeg", "jpe", "gif", "tif", "tiff", "webp", "ico",
    "ppm", "pgm", "pbm", "pnm", "tga", "pcx", "qoi", "jp2", "avif", "psd",
)

# Форматы со сжатием с потерями: встроенные LSB-данные в них не сохраняются.
LOSSY_FORMATS = {"JPEG", "MPO", "WEBP", "AVIF", "JPEG2000"}

_MODE_BITS = {"1": 1, "L": 8, "P": 8, "LA": 16, "I;16": 16, "RGB": 24, "YCbCr": 24,
              "LAB": 24, "HSV": 24, "RGBA": 32, "CMYK": 32, "I": 32, "F": 32}


def _bmp_bit_count(path: str) -> int | None:
    """Глубина цвета из заголовка BMP (Pillow её не сообщает)."""
    with open(path, "rb") as f:
        head = f.read(30)
    if len(head) < 30:
        return None
    offset = 24 if int.from_bytes(head[14:18], "little") == 12 else 28
    return int.from_bytes(head[offset:offset + 2], "little") or None


def load_image(path: str, normalize: bool = True) -> tuple[np.ndarray, str, str]:
    """Загружает изображение любого поддерживаемого формата и приводит его к BMP 24 бит.

    Возвращает массив (H, W, 3) uint8, описание и имя исходного формата.
    При normalize=True учитывается EXIF-ориентация, а прозрачность
    накладывается на белый фон (для контейнера); иначе берутся «сырые» RGB-значения
    (для извлечения, чтобы не исказить младшие биты).
    """
    notes = []
    try:
        with Image.open(path) as img:
            fmt = img.format or "?"
            frames = getattr(img, "n_frames", 1)
            img.seek(0)
            bits = (_bmp_bit_count(path) if fmt == "BMP" else None) or _MODE_BITS.get(img.mode, img.mode)
            if normalize:
                img = ImageOps.exif_transpose(img)
            has_alpha = img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info
            if has_alpha and normalize:
                rgba = img.convert("RGBA")
                img = Image.alpha_composite(Image.new("RGBA", rgba.size, "white"), rgba)
                notes.append("прозрачность заменена белым фоном")
            elif has_alpha:
                notes.append("альфа-канал отброшен")
            converted = fmt != "BMP" or bits != 24
            arr = np.array(img.convert("RGB"), dtype=np.uint8)
    except Exception as exc:  # noqa: BLE001 — Pillow бросает разные исключения
        raise StegoError(f"Не удалось открыть изображение: {exc}") from exc

    if frames > 1:
        notes.append(f"использован первый кадр из {frames}")
    if converted:
        notes.insert(0, "преобразовано в BMP 24 бит")
    info = f"{fmt}, {arr.shape[1]}×{arr.shape[0]} пикс., {bits} бит/пикс."
    if notes:
        info += " (" + "; ".join(notes) + ")"
    return np.ascontiguousarray(arr), info, fmt


def save_bmp(arr: np.ndarray, path: str) -> None:
    Image.fromarray(arr, "RGB").save(path, format="BMP")


def _validate(channels, planes, skip) -> tuple[list[int], list[int], int]:
    channels = sorted(set(channels))
    planes = sorted(set(planes))
    if not channels:
        raise StegoError("Не выбрана ни одна цветовая компонента.")
    if not planes:
        raise StegoError("Не выбрана ни одна битовая плоскость.")
    if any(c not in (0, 1, 2) for c in channels):
        raise StegoError("Недопустимая цветовая компонента.")
    if any(not 1 <= p <= MAX_PLANE for p in planes):
        raise StegoError(f"Допустимы битовые плоскости с 1 по {MAX_PLANE}.")
    if skip < 0:
        raise StegoError("Недопустимый интервал встраивания.")
    return channels, planes, skip + 1


def usable_pixels(shape, skip: int) -> int:
    return math.ceil(shape[0] * shape[1] / (skip + 1))


def capacity_bits(shape, channels, planes, skip: int) -> int:
    """Полная ёмкость контейнера в битах (включая заголовок длины)."""
    if not channels or not planes:
        return 0
    return usable_pixels(shape, skip) * len(set(channels)) * len(set(planes))


def capacity_bytes(shape, channels, planes, skip: int) -> int:
    """Максимальная длина сообщения в байтах."""
    return max(0, (capacity_bits(shape, channels, planes, skip) - HEADER_BITS) // 8)


def _read_bits(flat: np.ndarray, pix_idx: np.ndarray, channels, planes) -> np.ndarray:
    block = flat[pix_idx][:, channels]  # (N, C)
    shifts = np.array([p - 1 for p in planes], dtype=np.uint8)
    return ((block[:, :, None] >> shifts) & 1).astype(np.uint8).reshape(-1)


def embed(arr: np.ndarray, message: bytes, channels, planes, skip: int) -> np.ndarray:
    """Встраивает сообщение и возвращает новый массив изображения."""
    channels, planes, step = _validate(channels, planes, skip)
    if not message:
        raise StegoError("Сообщение пустое.")
    payload = len(message).to_bytes(4, "big") + message
    bits = np.unpackbits(np.frombuffer(payload, dtype=np.uint8))

    cap = capacity_bits(arr.shape, channels, planes, skip)
    if bits.size > cap:
        raise StegoError(
            f"Сообщение не помещается в контейнер: требуется {bits.size} бит, "
            f"доступно {cap} бит (не более {capacity_bytes(arr.shape, channels, planes, skip)} байт)."
        )

    per_pixel = len(channels) * len(planes)
    n_pix = math.ceil(bits.size / per_pixel)
    flat = arr.reshape(-1, 3).copy()
    pix_idx = np.arange(0, flat.shape[0], step)[:n_pix]

    # Берём текущие биты, чтобы «хвост» последнего пикселя остался неизменным.
    slots = _read_bits(flat, pix_idx, channels, planes)
    slots[: bits.size] = bits
    slots = slots.reshape(n_pix, len(channels), len(planes))

    shifts = np.array([p - 1 for p in planes], dtype=np.uint8)
    mask = np.uint8(sum(1 << s for s in shifts.tolist()))
    new_bits = (slots << shifts).sum(axis=2).astype(np.uint8)

    block = flat[pix_idx][:, channels]
    block = (block & ~mask) | new_bits
    sub = flat[pix_idx]
    sub[:, channels] = block
    flat[pix_idx] = sub
    return flat.reshape(arr.shape)


def extract(arr: np.ndarray, channels, planes, skip: int) -> bytes:
    """Извлекает сообщение, встроенное с теми же параметрами."""
    channels, planes, step = _validate(channels, planes, skip)
    flat = arr.reshape(-1, 3)
    all_idx = np.arange(0, flat.shape[0], step)
    per_pixel = len(channels) * len(planes)

    cap = all_idx.size * per_pixel
    if cap < HEADER_BITS:
        raise StegoError("Контейнер слишком мал для извлечения при данных параметрах.")

    header_pix = math.ceil(HEADER_BITS / per_pixel)
    header = _read_bits(flat, all_idx[:header_pix], channels, planes)[:HEADER_BITS]
    length = int.from_bytes(np.packbits(header).tobytes(), "big")

    max_len = (cap - HEADER_BITS) // 8
    if length == 0 or length > max_len:
        raise StegoError(
            f"Сообщение не обнаружено: прочитанная длина ({length} байт) "
            f"некорректна для данного контейнера (допустимо от 1 до {max_len}).\n"
            "Проверьте, что выбраны те же компоненты, плоскости и интервал, что и при встраивании."
        )

    total = HEADER_BITS + length * 8
    n_pix = math.ceil(total / per_pixel)
    bits = _read_bits(flat, all_idx[:n_pix], channels, planes)[HEADER_BITS:total]
    return np.packbits(bits).tobytes()


def bit_plane(arr: np.ndarray, channel: int, plane: int) -> np.ndarray:
    """Изображение битовой плоскости (plane: 1..8) в виде RGB-массива."""
    mono = ((arr[:, :, channel] >> (plane - 1)) & 1) * 255
    return np.repeat(mono[:, :, None], 3, axis=2).astype(np.uint8)


def metrics(original: np.ndarray, stego: np.ndarray) -> tuple[float, float, int]:
    """Возвращает (MSE, PSNR в дБ, число изменённых пикселей)."""
    diff = original.astype(np.int16) - stego.astype(np.int16)
    mse = float(np.mean(diff.astype(np.float64) ** 2))
    psnr = float("inf") if mse == 0 else 10 * math.log10(255 ** 2 / mse)
    changed = int(np.count_nonzero(np.any(diff != 0, axis=2)))
    return mse, psnr, changed
