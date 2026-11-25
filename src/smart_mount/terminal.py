"""Portable terminal presentation for GROTAXE SMART MOUNT."""

import os
import shutil
import sys


TITLE = "GROTAXE SMART MOUNT"
SUBTITLE = "LINUX STORAGE PROTECTION"

COLORS = {
    "green": "\033[1;92m",
    "white": "\033[97m",
    "shadow": "\033[2;32m",
    "cyan": "\033[36m",
    "red": "\033[1;31m",
    "amber": "\033[33m",
    "muted": "\033[2m",
    "reset": "\033[0m",
}

FONT = {
    "S": ("#####", "#    ", "#####", "    #", "#####"),
    "M": ("#   #", "## ##", "# # #", "#   #", "#   #"),
    "A": (" ### ", "#   #", "#####", "#   #", "#   #"),
    "R": ("#### ", "#   #", "#### ", "#  # ", "#   #"),
    "T": ("#####", "  #  ", "  #  ", "  #  ", "  #  "),
    "O": (" ### ", "#   #", "#   #", "#   #", " ### "),
    "U": ("#   #", "#   #", "#   #", "#   #", " ### "),
    "N": ("#   #", "##  #", "# # #", "#  ##", "#   #"),
}


def safe_text(value):
    """Prevent terminal control sequence injection."""
    return "".join(
        character if character.isprintable() else "?"
        for character in str(value)
    )


class Terminal:

    def __init__(self, stream=None, *, plain=False):
        self.stream = sys.stdout if stream is None else stream
        self.plain = plain or not self.stream.isatty()

        self.color = (
            not self.plain
            and "NO_COLOR" not in os.environ
            and os.environ.get("TERM") != "dumb"
        )

    def paint(self, value, tone):
        value = safe_text(value)

        if not self.color:
            return value

        return COLORS[tone] + value + COLORS["reset"]

    def emit(self, value=""):
        print(value, file=self.stream)

    def width(self):
        columns = shutil.get_terminal_size((80, 24)).columns
        return max(20, min(columns, 76))

    def unicode_available(self):
        encoding = getattr(self.stream, "encoding", None)

        try:
            "┌─┐│└┘█▓".encode(encoding or "utf-8")
        except (UnicodeError, LookupError):
            return False

        return True

    def line(self):
        if not self.plain:
            symbol = "─" if self.unicode_available() else "="
            self.emit(
                self.paint(symbol * self.width(), "cyan")
            )

    def logo_rows(self):
        pixels = set()

        for y in range(5):
            row = "   ".join(
                " ".join(FONT[letter][y] for letter in word)
                for word in ("SMART", "MOUNT")
            )

            for x, character in enumerate(row):
                if character == "#":
                    pixels.add((x, y))

        width = max(x for x, y in pixels) + 2

        rows = []

        for y in range(6):
            row = []

            for x in range(width):
                if (x, y) in pixels:
                    row.append("█")
                elif (x - 1, y - 1) in pixels:
                    row.append("▓")
                else:
                    row.append(" ")

            rows.append("".join(row))

        return rows

    def banner(self, subtitle=SUBTITLE):
        if self.plain:
            self.emit(TITLE)
            self.emit(safe_text(subtitle))
            return

        if self.width() < 66 or not self.unicode_available():
            self.line()
            self.emit(self.paint(TITLE, "green"))
            self.emit(self.paint(subtitle, "cyan"))
            self.line()
            return

        from itertools import groupby

        inner = self.width() - 2
        edge = self.paint("│", "cyan")

        def framed(value="", tone="white"):
            content = safe_text(value).center(inner)
            self.emit(edge + self.paint(content, tone) + edge)

        self.emit(
            self.paint("┌" + "─" * inner + "┐", "cyan")
        )

        framed()
        framed("G R O T A X E", "white")
        framed()

        for row in self.logo_rows():
            parts = []

            for character, group in groupby(row.center(inner)):
                value = "".join(group)

                if character == "█":
                    value = self.paint(value, "green")
                elif character == "▓":
                    value = self.paint(value, "shadow")

                parts.append(value)

            self.emit(edge + "".join(parts) + edge)

        framed()
        framed(subtitle, "cyan")
        framed()

        self.emit(
            self.paint("└" + "─" * inner + "┘", "cyan")
        )

    def menu_item(self, option, description):
        number = safe_text(option).ljust(4)

        self.emit(
            self.paint(number, "green")
            + " "
            + self.paint(description, "white")
        )

    def heading(self, value):
        self.emit()
        self.emit(self.paint(value, "cyan"))
        self.line()

    def field(self, label, value):
        self.emit(
            f"{safe_text(label):<22} {safe_text(value)}"
        )

    def status(self, ok, message):
        label = "[ OK ]" if ok else "[FAIL]"
        tone = "green" if ok else "red"

        self.emit(
            self.paint(label, tone) + " " + safe_text(message)
        )
