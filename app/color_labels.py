COLOR_LABELS = {
    "lemon": "Потенциальный",
    "yellow": "Встреча",
    "orange": "Открыть счет",
    "light_green": "Завод денег",
    "red": "Отказ",
    "light_lilac": "Потенциальный агент",
    "purple": "Агент",
    "brown": "Коричневый",
    "blue": "Контакт свой",
    "black": "Чёрный",
    "gray": "Серый",
}


def validate_color_label(value):
    if value not in {"", *COLOR_LABELS}:
        raise ValueError("Выберите цветовую метку из списка.")
    return value
