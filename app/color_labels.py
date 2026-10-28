COLOR_LABELS = {
    "lemon": "Лимонный",
    "yellow": "Жёлтый",
    "orange": "Оранжевый",
    "red": "Красный",
    "light_green": "Светло-зелёный",
    "gray": "Серый",
}


def validate_color_label(value):
    if value not in {"", *COLOR_LABELS}:
        raise ValueError("Выберите цветовую метку из списка.")
    return value
