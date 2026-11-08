"""Dinh dang hien thi kieu Viet Nam cho van ban sinh tu backend (ly do de xuat, canh bao)."""
from datetime import date


def vnd(v) -> str:
    return f"{int(round(v)):,}".replace(",", ".") + "đ"


def dmy(d) -> str:
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    return d.strftime("%d/%m/%Y")
