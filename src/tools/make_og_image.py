"""FRNC 공유 미리보기(og:image) 1200×630 PNG 생성기.

실행: python3 src/tools/make_og_image.py   → static/og.png 갱신
Pillow 는 생성 시점에만 쓰고, 서버 런타임은 표준 라이브러리만 쓴다(생성된 PNG 만 읽는다).
이미지가 없으면 `static_files.load_og_image()` 가 표준 라이브러리로 글자 없는 브랜드 PNG 를 만든다.
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
BG_TOP = (11, 16, 28)
BG_BOTTOM = (18, 28, 52)
BRAND = (31, 79, 216)
BRAND_SOFT = (140, 168, 255)
INK = (232, 237, 245)
INK_SOFT = (159, 179, 217)
LINE = (42, 58, 95)

CJK = "/usr/share/fonts/pickle-hwp/NotoSansCJKkr-Regular.otf"
LATIN_BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"

CHIPS = ["정보공개서 14일", "가맹금 예치", "예상매출 서면", "영업지역"]


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _base_gradient() -> Image.Image:
    image = Image.new("RGB", (W, H), BG_TOP)
    draw = ImageDraw.Draw(image)
    for y in range(H):
        ratio = y / (H - 1)
        color = tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * ratio) for i in range(3))
        draw.line([(0, y), (W, y)], fill=color)
    return image


def _blend_glow(base: Image.Image) -> Image.Image:
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    for radius in range(460, 0, -6):
        strength = (1 - radius / 460) ** 2
        gdraw.ellipse([W - 240 - radius, -180 - radius, W - 240 + radius, -180 + radius],
                      fill=(int(32 * strength), int(52 * strength), int(128 * strength)))
    return Image.blend(base, glow, 0.55)


def rounded(draw: ImageDraw.ImageDraw, box, radius, fill=None, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def build() -> Image.Image:
    image = _blend_glow(_base_gradient())
    draw = ImageDraw.Draw(image)
    left = 88

    rounded(draw, [left, 74, left + 66, 140], 18, fill=BRAND)
    draw.text((left + 33, 107), "F", font=font(LATIN_BOLD, 40), fill=(255, 255, 255), anchor="mm")

    draw.text((left + 86, 84), "FRNC", font=font(LATIN_BOLD, 76), fill=INK)
    draw.text((left + 90, 168), "KOREA FRANCHISE DISCLOSURE RISK CHECK",
              font=font(LATIN_BOLD, 21), fill=INK_SOFT)

    draw.line([(left, 236), (W - left, 236)], fill=LINE, width=2)

    draw.text((left, 274), "프랜차이즈 계약 전, 10초 리스크 체크", font=font(CJK, 46), fill=INK)
    draw.text((left, 344), "정보공개서와 가맹사업법 조문으로 확인할 신호를 정리합니다",
              font=font(CJK, 29), fill=INK_SOFT)

    x = left
    for label in CHIPS:
        label_font = font(CJK, 22)
        width = int(draw.textlength(label, font=label_font)) + 40
        rounded(draw, [x, 404, x + width, 458], 27, fill=None, outline=LINE, width=2)
        draw.text((x + 20, 431), label, font=label_font, fill=BRAND_SOFT, anchor="lm")
        x += width + 14

    draw.text((left, 492), "확인 필요 신호 있음 / 정보 부족 / 뚜렷한 위험 신호 없음",
              font=font(CJK, 23), fill=INK_SOFT)

    draw.line([(left, 552), (W - left, 552)], fill=LINE, width=2)
    draw.text((left, 574), "frnc.onrender.com", font=font(LATIN_BOLD, 26), fill=INK)
    draw.text((W - left, 578), "무료 베타 · 로그인 없음 · 확정 판정 아님",
              font=font(CJK, 21), fill=INK_SOFT, anchor="ra")
    return image


def main() -> int:
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "static", "og.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    image = build()
    image.save(out, "PNG", optimize=True)
    print(f"wrote {out} ({os.path.getsize(out)} bytes, {image.width}x{image.height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
