import os
import sys
import time

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
    os.system("cls" if os.name == "nt" else "clear")


def _flush_stdin_buffer():
    """Вычитывает из stdin все, что накопилось (Windows).

    Используется внутри pause(): к моменту "Нажми Enter" в буфере может
    лежать остаток '\r\n' от нажатия '0' при остановке дочернего процесса,
    а также случайные клавиши. Без сброса следующий input() принял бы
    этот остаток за пустой Enter, и пользователь не увидел бы приглашения.
    """
    if os.name != "nt":
        return
    try:
        import msvcrt

        while msvcrt.kbhit():
            msvcrt.getch()
    except Exception:
        pass


def pause():
    _flush_stdin_buffer()
    input("\nНажми Enter для продолжения...")


def ask_yes_no(prompt, allow_cancel=False):
    """Д/Н. Если allow_cancel - '0' возвращает None (отмена)."""
    yes = {"д", "да", "y", "yes"}
    no = {"н", "нет", "n", "no"}
    hint = " (д/н, 0 - отмена)" if allow_cancel else " (д/н)"
    while True:
        ans = input(f"{prompt}{hint}: ").strip().lower()
        if allow_cancel and ans == "0":
            return None
        if ans in yes:
            return True
        if ans in no:
            return False
        if allow_cancel:
            print_error("Введи 'д' (да), 'н' (нет) или '0' (отмена).")
        else:
            print_error("Введи 'д' (да) или 'н' (нет).")


def ask_choice(prompt, options, allow_cancel=False, cancel_label="Отмена"):
    print()
    print(prompt)
    print()
    for i, (_, label, description) in enumerate(options, 1):
        print(f"  {i}. {label}")
        if description:
            for line in description.split("\n"):
                print(f"     {line}")
    if allow_cancel:
        print(f"  0. {cancel_label}")

    while True:
        ans = input("\nТвой выбор: ").strip()
        if allow_cancel and ans == "0":
            return None
        if ans.isdigit():
            idx = int(ans)
            if 1 <= idx <= len(options):
                return options[idx - 1][0]
        if allow_cancel:
            print_error(f"Введи число 1-{len(options)} или 0 для отмены.")
        else:
            print_error(f"Введи число 1-{len(options)}.")


def ask_int(prompt, allow_cancel=False, min_value=None, max_value=None):
    while True:
        val = input(prompt).strip()
        if allow_cancel and val == "0":
            return None
        if not val:
            print_error("Введи число.")
            continue
        try:
            num = int(val)
        except ValueError:
            print_error("Введи целое число.")
            continue
        if min_value is not None and num < min_value:
            print_error(f"Значение должно быть >= {min_value}.")
            continue
        if max_value is not None and num > max_value:
            print_error(f"Значение должно быть <= {max_value}.")
            continue
        return num


def check_stop_key():
    """Неблокирующая проверка '0'. Вычитывает весь буфер после нажатия."""
    try:
        if os.name == "nt":
            import msvcrt

            if msvcrt.kbhit():
                ch = msvcrt.getch()
                # Вычитываем весь хвост (обычно \r\n после Enter),
                # чтобы он не попал в следующий input().
                while msvcrt.kbhit():
                    msvcrt.getch()
                if ch == b"0":
                    return True
            return False
        else:
            import select

            if sys.stdin.isatty():
                rlist, _, _ = select.select([sys.stdin], [], [], 0)
                if rlist:
                    ch = sys.stdin.read(1)
                    if ch == "0":
                        return True
    except Exception:
        pass
    return False


def wait_with_stop(seconds):
    """Ожидание с возможностью раннего выхода по '0'."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if check_stop_key():
            return True
        time.sleep(0.2)
    return False
