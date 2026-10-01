"""Terminal input and output for SafeReport"""

def display_menu() -> None:
    """Display the menu."""
    print("\nSafeReport!")
    print("----------")
    print("1. Create a new safety report")
    print("0. Exit")

def get_menu_choice() -> str:
    """Return a valid menu choice, or '0' if input is cancelled"""

    while True:
        try:
            choice = input("Select an option: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nInput cancelled.")
            return "0"

        if choice == "1" or choice == "0":
            return choice

        print ("invalid choice. Please enter 1 or 0.")

def get_report_text() -> str | None:
    """Collect report description, or return none if cancelled"""
    print("\nDescribe what you observed, then press Enter to submit.")
    print("Press Ctrl+C to cancel.")

    try:
        return input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nReport entry cancelled.")
        return None