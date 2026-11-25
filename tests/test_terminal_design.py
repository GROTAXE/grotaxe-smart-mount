import io
import re
import unittest

from unittest.mock import patch

from smart_mount.terminal import Terminal


class TerminalStream(io.StringIO):

    def isatty(self):
        return True


class ASCIITerminal(TerminalStream):

    @property
    def encoding(self):
        return "ascii"


class TerminalDesignTests(unittest.TestCase):

    def test_framed_logo(self):
        stream = TerminalStream()

        with patch.dict(
            "os.environ", {"TERM": "xterm"}, clear=True
        ):
            ui = Terminal(stream)

            with patch.object(ui, "width", return_value=76):
                ui.banner("INSTALLATION WIZARD")

        output = stream.getvalue()
        plain = re.sub(r"\x1b\[[0-9;]*m", "", output)

        self.assertIn("█", plain)
        self.assertIn("▓", plain)
        self.assertIn("┌", plain)
        self.assertIn("┘", plain)
        self.assertIn("G R O T A X E", plain)
        self.assertIn("INSTALLATION WIZARD", plain)

        for line in plain.splitlines():
            self.assertEqual(len(line), 76)

    def test_plain_fallback(self):
        stream = io.StringIO()
        Terminal(stream, plain=True).banner()

        self.assertIn(
            "GROTAXE SMART MOUNT",
            stream.getvalue(),
        )

        self.assertNotIn("\033", stream.getvalue())

    def test_narrow_terminal(self):
        stream = TerminalStream()
        ui = Terminal(stream)

        with patch.object(ui, "width", return_value=40):
            ui.banner()

        self.assertIn(
            "GROTAXE SMART MOUNT",
            stream.getvalue(),
        )

        self.assertNotIn("█", stream.getvalue())

    def test_ascii_terminal(self):
        stream = ASCIITerminal()
        ui = Terminal(stream)

        with patch.object(ui, "width", return_value=76):
            ui.banner()

        stream.getvalue().encode("ascii")

    def test_no_color(self):
        stream = TerminalStream()

        with patch.dict(
            "os.environ",
            {"TERM": "xterm", "NO_COLOR": "1"},
            clear=True,
        ):
            ui = Terminal(stream)

            with patch.object(ui, "width", return_value=76):
                ui.banner()

        self.assertNotIn("\033", stream.getvalue())
        self.assertIn("█", stream.getvalue())

    def test_menu_alignment(self):
        stream = io.StringIO()
        ui = Terminal(stream, plain=True)

        ui.menu_item("01", "Automatic configuration")

        self.assertEqual(
            stream.getvalue(),
            "01   Automatic configuration\n",
        )


if __name__ == "__main__":
    unittest.main()
