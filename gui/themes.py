"""
themes.py — цветовые темы, палитра и вспомогательная функция T().
"""

MONTHS = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]

THEMES = {
    "Тёмная": {
        "mode": "dark",
        "BG_DEEP": "#0F1117", "BG_PANEL": "#161B27", "BG_CARD": "#1E2435",
        "BG_CARD_HVR": "#252B3B", "ACCENT": "#3B82F6", "ACCENT_LIGHT": "#60A5FA",
        "ACCENT_DIM": "#1D3461", "SUCCESS": "#10B981", "WARNING": "#F59E0B",
        "DANGER": "#EF4444", "TEXT_PRI": "#F1F5F9", "TEXT_SEC": "#94A3B8",
        "TEXT_DIM": "#475569", "BORDER": "#2D3748",
    },
    "Светлая": {
        "mode": "light",
        "BG_DEEP": "#F0F2F5", "BG_PANEL": "#E8EBF0", "BG_CARD": "#FFFFFF",
        "BG_CARD_HVR": "#F5F7FA", "ACCENT": "#2563EB", "ACCENT_LIGHT": "#3B82F6",
        "ACCENT_DIM": "#DBEAFE", "SUCCESS": "#059669", "WARNING": "#D97706",
        "DANGER": "#DC2626", "TEXT_PRI": "#0F172A", "TEXT_SEC": "#475569",
        "TEXT_DIM": "#94A3B8", "BORDER": "#CBD5E1",
    },
    "Серая": {
        "mode": "dark",
        "BG_DEEP": "#1A1A1A", "BG_PANEL": "#222222", "BG_CARD": "#2A2A2A",
        "BG_CARD_HVR": "#333333", "ACCENT": "#6366F1", "ACCENT_LIGHT": "#818CF8",
        "ACCENT_DIM": "#2E2E5A", "SUCCESS": "#10B981", "WARNING": "#F59E0B",
        "DANGER": "#EF4444", "TEXT_PRI": "#F8FAFC", "TEXT_SEC": "#9CA3AF",
        "TEXT_DIM": "#4B5563", "BORDER": "#3A3A3A",
    },
}

CURRENT_THEME: dict = THEMES["Тёмная"]


def T(key: str) -> str:
    """Возвращает цвет из текущей темы по ключу."""
    return CURRENT_THEME[key]
