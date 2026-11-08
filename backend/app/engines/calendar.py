from datetime import date, timedelta

# Mung 1 Tet Nguyen Dan
TET_DATES = {
    2023: date(2023, 1, 22),
    2024: date(2024, 2, 10),
    2025: date(2025, 1, 29),
    2026: date(2026, 2, 17),
    2027: date(2027, 2, 6),
    2028: date(2028, 1, 26),
}

PHASES = ("pre_tet", "tet", "post_tet")


def tet_phase(d: date) -> str | None:
    """pre_tet: 10 ngay truoc Tet; tet: mung 1 -> mung 6; post_tet: mung 7 -> mung 11."""
    for tet in TET_DATES.values():
        delta = (d - tet).days
        if -10 <= delta <= -1:
            return "pre_tet"
        if 0 <= delta <= 5:
            return "tet"
        if 6 <= delta <= 10:
            return "post_tet"
    return None


def daterange(start: date, days: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(days)]


WEEKDAY_VI = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
