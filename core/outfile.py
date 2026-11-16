"""Проверка выходного файла ДО начала генерации (иначе ошибка всплывает в самом конце)."""
import os


class OutputNotWritable(Exception):
    """Результат некуда записать; текст сообщения можно показывать пользователю как есть."""


def check_output_writable(path: str) -> None:
    """Пробует открыть файл на дозапись. Существующий файл не меняется, новый не остаётся.

    Файл, открытый в Excel, в Windows недоступен для записи — об этом лучше узнать сразу,
    а не после чтения источника и шаблона."""
    folder = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(folder):
        raise OutputNotWritable(f"Папка для результата не существует:\n{folder}")
    existed = os.path.exists(path)
    try:
        with open(path, "ab"):
            pass
    except PermissionError:
        raise OutputNotWritable(
            f"Не удаётся записать файл:\n{path}\n\n"
            "Закройте его (возможно, он открыт в Excel) или выберите другое имя."
        ) from None
    except OSError as e:
        raise OutputNotWritable(f"Не удаётся записать файл:\n{path}\n\n{e.strerror or e}") from None
    if not existed:
        try:
            os.remove(path)
        except OSError:
            pass
