from __future__ import annotations

import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.email_alerts import build_alert_email


class EmailAlertTemplateTests(unittest.TestCase):
    def test_build_alert_email_renders_branded_html(self) -> None:
        email = build_alert_email(
            title="Nouvelle alerte projet",
            summary="Le workspace est pret et un point de vigilance a ete detecte.",
            severity="warning",
            project_name="QrHunt",
            project_id="proj-123",
            details=[
                "Validation admin requise avant de poursuivre",
                "Le dossier reste confine au workspace",
            ],
            action_label="Ouvrir le projet",
            action_url="https://example.com/projects/proj-123",
            footer_note="Reponse attendue sous 24 h.",
        )

        self.assertIn("AIA Studio - Alerte - Nouvelle alerte projet", email.subject)
        self.assertIn("<html lang=\"fr\">", email.html)
        self.assertIn("background: linear-gradient", email.html)
        self.assertIn("QrHunt", email.html)
        self.assertIn("proj-123", email.html)
        self.assertIn("Validation admin requise avant de poursuivre", email.html)
        self.assertIn("Ouvrir le projet", email.html)
        self.assertIn("https://example.com/projects/proj-123", email.html)
        self.assertIn("Reponse attendue sous 24 h.", email.text)
        self.assertIn("Details:", email.text)
        self.assertIn("- Validation admin requise avant de poursuivre", email.text)

    def test_build_alert_email_escapes_html_content(self) -> None:
        email = build_alert_email(
            title="Alerte <critique>",
            summary='Contenu avec <script>alert("x")</script>.',
            severity="error",
            details=['Balise "dangereuse" & test'],
        )

        self.assertNotIn("<script>", email.html)
        self.assertIn("&lt;critique&gt;", email.html)
        self.assertIn("&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;", email.html)
        self.assertIn("Balise &quot;dangereuse&quot; &amp; test", email.html)


def main() -> None:
    unittest.main()


if __name__ == "__main__":
    main()
