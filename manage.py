import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Work.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Не удалось импортировать Django. Вы уверены, что она установлена и доступна в переменной окружения PYTHONPATH? Вы забыли активировать виртуальное окружение?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
