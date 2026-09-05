"""프로토타입의 단색 라인 아이콘 세트 (1.5px, 이모지 없음)."""
from __future__ import annotations

from markupsafe import Markup

IC: dict[str, str] = {
    "bell": '<path d="M6 9a6 6 0 0 1 12 0c0 6 2 7 2 7H4s2-1 2-7"/><path d="M10 20a2 2 0 0 0 4 0"/>',
    "shield": '<path d="M12 3l7 2.5V11c0 4.6-3 7.6-7 9-4-1.4-7-4.4-7-9V5.5z"/><path d="M9 12l2 2 4-4"/>',
    "lock": '<rect x="5" y="10.5" width="14" height="9.5" rx="2"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5"/>',
    "scissors": '<circle cx="6.5" cy="6.5" r="2.3"/><circle cx="6.5" cy="17.5" r="2.3"/><path d="M8.4 7.8L19 18M8.4 16.2L19 6"/>',
    "meal": '<path d="M4 11h16a8 8 0 0 1-16 0z"/><path d="M3 11h18"/><path d="M9.5 4c0 1.6-1 1.6-1 3.2M14.5 4c0 1.6-1 1.6-1 3.2"/>',
    "bag": '<path d="M6 8.5h12l-1 11.5H7z"/><path d="M9 8.5a3 3 0 0 1 6 0"/>',
    "fix": '<path d="M9 4.2a4 4 0 0 0 5.3 5.3l5 5a1.6 1.6 0 0 1-2.3 2.3l-5-5A4 4 0 0 1 6.7 6.5z"/>',
    "basket": '<path d="M4.5 9.5h15l-1.6 10H6.1z"/><path d="M5 9.5l3-5M19 9.5l-3-5"/>',
    "heart": '<path d="M12 20s-7-4.6-7-10.2A3.8 3.8 0 0 1 12 7a3.8 3.8 0 0 1 7-2.2C19 14.4 12 20 12 20z" stroke-linejoin="round"/>',
    "pen": '<path d="M5 19l1.2-4L16 5.2 18.8 8 9 17.8z"/><path d="M14.5 6.7l2.8 2.8"/>',
    "doc": '<path d="M7 3.5h7L18 7.5V20.5H7z"/><path d="M14 3.5v4h4"/><path d="M9.5 12.5h6M9.5 16h6"/>',
    "compass": '<circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2.3 5.2-5.2 2.3 2.3-5.2z" stroke-linejoin="round"/>',
    "link": '<path d="M9.5 12h5"/><path d="M10.5 8.5H9a3.5 3.5 0 0 0 0 7h1.5M13.5 8.5H15a3.5 3.5 0 0 1 0 7h-1.5"/>',
    "chart": '<path d="M4 20h16"/><path d="M7 20v-7M12 20V7M17 20v-4"/>',
    "building": '<rect x="5.5" y="4" width="13" height="16"/><path d="M9 8h2M13 8h2M9 11.5h2M13 11.5h2M9 15h2M13 15h2"/><path d="M5.5 20h13"/>',
    "users": '<circle cx="9.5" cy="9" r="3"/><path d="M4 19a5.5 5.5 0 0 1 11 0"/><path d="M16 6.2a3 3 0 0 1 0 5.6M20 18.5a5.5 5.5 0 0 0-3.5-5"/>',
    "user": '<circle cx="12" cy="8.5" r="3.4"/><path d="M5.5 20a6.5 6.5 0 0 1 13 0"/>',
    "store": '<path d="M4.5 9l1.4-4.5h12.2L19.5 9"/><path d="M4.5 9a2.4 2.4 0 0 0 4.7 0 2.4 2.4 0 0 0 4.6 0 2.4 2.4 0 0 0 4.7 0"/><path d="M6 11v9h12v-9"/>',
    "award": '<circle cx="12" cy="9" r="4.6"/><path d="M9.4 12.8L8 20l4-2.4 4 2.4-1.4-7.2"/>',
    "plus": '<path d="M12 6v12M6 12h12"/>',
    "check": '<path d="M5 12.5l4 4 10-10"/>',
    "chevl": '<path d="M14 6l-6 6 6 6"/>',
    "chevd": '<path d="M7 10l5 5 5-5"/>',
    "out": '<path d="M14 8V5.5H5v13h9V16"/><path d="M11 12h9"/><path d="M17.5 9l3 3-3 3"/>',
}

# 나눔 종류 → 아이콘
KIND_ICON = {"goods": "bag", "service": "fix", "meal": "meal", "repair": "fix"}


def icon(name: str) -> Markup:
    body = IC.get(name, IC["heart"])
    return Markup(
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" '
        'stroke-linecap="round" stroke-linejoin="round" width="100%" height="100%">'
        f"{body}</svg>"
    )
