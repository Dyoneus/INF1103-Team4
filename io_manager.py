"""Terminal input and output for SafeReport"""

MAX_DESCRIPTION_LENGTH = 2000 ; """The maximum length of a safety report description."""

"""Menu func starts here"""
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



"""Collect description starts here"""
def get_report_text() -> str | None:
    """Collect report description, or return None if cancelled"""
    print("\nDescribe what you observed, then press Enter to submit.")
    print(f"Maximum length: {MAX_DESCRIPTION_LENGTH} characters.")
    print("Press Ctrl+C to cancel.")

    while True:
        try:
            description = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nReport entry cancelled.")
            return None


        errors = validate_report_text(description, MAX_DESCRIPTION_LENGTH)

        if not errors:
            return description

        for error in errors:
            if error == "EMPTY_DESCRIPTION":
                print("Description cannot be empty. Please try again.")
            elif error == "DESCRIPTION_TOO_LONG":
                print(f"Description exceeds {MAX_DESCRIPTION_LENGTH} characters.")

"""Validation check for description"""
def validate_report_text(text: str, max_chars: int) -> list[str]:
    """if error, return error codes for blank & over-length descriptions."""
    text=text.strip()
    errors = []
    
    if not text:
        errors.append("EMPTY_DESCRIPTION")

    if len(text) > max_chars:
        errors.append("DESCRIPTION_TOO_LONG")

    return errors



"""For running io_manager.py easily/debugging"""
if __name__ == "__main__":
    display_menu()
    choice = get_menu_choice()

    if choice == "1":
        report_text = get_report_text()

        if report_text is not None:
            print("\nReport collected:")
            print(report_text)

    elif choice == "0":
        print("Exiting SafeReport.")