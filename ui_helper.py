import os
import sys

# ANSI-коды для цветного текста
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"


def print_success(text):
    print(f"{GREEN}✅ {text}{RESET}")


def print_error(text):
    print(f"{RED}⚠️ Ошибка: {text}{RESET}")


def print_warning(text):
    print(f"{YELLOW}{text}{RESET}")


def print_info(text):
    print(f"{CYAN}{text}{RESET}")


def clear_screen():
    """Очищает экран терминала для аккуратного вида."""
    os.system("cls" if os.name == "nt" else "clear")


def pause():
    input("\nНажми Enter для продолжения...")


def ask_yes_no(prompt):
    """
    Универсальный вопрос Да/Нет.
    Поддерживает русские (д/н) и английские (y/n) буквы.
    Защищен от случайного ввода слов.
    """
    while True:
        ans = input(f"{prompt} (д/н): ").strip().lower()
        if ans in ("д", "да", "y", "yes"):
            return True
        elif ans in ("н", "нет", "n", "no"):
            return False
        else:
            print_error("Пожалуйста, введи 'д' (да) или 'н' (нет).")
