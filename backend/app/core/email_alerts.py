from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Iterable


@dataclass(frozen=True)
class AlertEmail:
    subject: str
    html: str
    text: str


_SEVERITY_STYLES = {
    "info": {
        "label": "Information",
        "accent": "#2563eb",
        "soft": "#dbeafe",
        "text": "#1e3a8a",
    },
    "success": {
        "label": "Succes",
        "accent": "#16a34a",
        "soft": "#dcfce7",
        "text": "#14532d",
    },
    "warning": {
        "label": "Alerte",
        "accent": "#d97706",
        "soft": "#fef3c7",
        "text": "#78350f",
    },
    "error": {
        "label": "Erreur",
        "accent": "#dc2626",
        "soft": "#fee2e2",
        "text": "#7f1d1d",
    },
}


def _severity_palette(severity: str) -> dict[str, str]:
    return _SEVERITY_STYLES.get((severity or "info").strip().lower(), _SEVERITY_STYLES["info"])


def _normalize_lines(values: Iterable[str] | None) -> list[str]:
    if not values:
        return []
    lines: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text:
            lines.append(text)
    return lines


def _build_text_body(
    *,
    brand_name: str,
    title: str,
    summary: str,
    severity_label: str,
    project_name: str | None,
    project_id: str | None,
    details: list[str],
    action_label: str | None,
    action_url: str | None,
    footer_note: str | None,
) -> str:
    lines = [
        f"{brand_name} - {severity_label}",
        "",
        title.strip(),
        "",
        summary.strip(),
    ]
    if project_name:
        lines.extend(["", f"Projet: {project_name}"])
    if project_id:
        lines.append(f"Projet ID: {project_id}")
    if details:
        lines.extend(["", "Details:"])
        lines.extend([f"- {item}" for item in details])
    if action_label and action_url:
        lines.extend(["", f"{action_label}: {action_url}"])
    if footer_note:
        lines.extend(["", footer_note.strip()])
    lines.extend(["", f"{brand_name}"])
    return "\n".join(lines).strip() + "\n"


def build_alert_email(
    *,
    title: str,
    summary: str,
    severity: str = "info",
    brand_name: str = "AIA Studio",
    project_name: str | None = None,
    project_id: str | None = None,
    details: Iterable[str] | None = None,
    action_label: str | None = None,
    action_url: str | None = None,
    footer_note: str | None = None,
) -> AlertEmail:
    palette = _severity_palette(severity)
    normalized_details = _normalize_lines(details)
    safe_brand = escape(brand_name)
    safe_title = escape(title.strip())
    safe_summary = escape(summary.strip())
    safe_project_name = escape(project_name.strip()) if project_name else ""
    safe_project_id = escape(project_id.strip()) if project_id else ""
    safe_details = [escape(item) for item in normalized_details]
    safe_action_label = escape(action_label.strip()) if action_label else ""
    safe_action_url = escape(action_url.strip()) if action_url else ""
    safe_footer = escape(footer_note.strip()) if footer_note else ""

    subject_parts = [brand_name.strip(), palette["label"], title.strip()]
    subject = " - ".join([part for part in subject_parts if part])

    detail_cards = ""
    if safe_project_name or safe_project_id:
        detail_cards += f"""
                <tr>
                  <td style=\"padding: 0 8px 0 0;\">
                    <table role=\"presentation\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\" width=\"100%\">
                      <tr>
                        <td style=\"border: 1px solid #e5e7eb; border-radius: 14px; padding: 14px 16px; background: #ffffff;\">
                          <div style=\"font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; color: #6b7280; margin-bottom: 6px;\">Contexte</div>
                          <div style=\"font-size: 15px; color: #111827; font-weight: 700; line-height: 1.4;\">{safe_project_name or 'Projet'}</div>
                          {f'<div style=\"margin-top: 4px; font-size: 13px; color: #6b7280;\">ID {safe_project_id}</div>' if safe_project_id else ''}
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
        """

    details_html = ""
    if safe_details:
        items = "".join(
            f"<li style=\"margin: 0 0 10px 0;\">{item}</li>"
            for item in safe_details
        )
        details_html = f"""
                <tr>
                  <td style=\"padding-top: 20px;\">
                    <div style=\"font-size: 13px; font-weight: 700; color: #111827; margin-bottom: 10px;\">Points a retenir</div>
                    <ul style=\"margin: 0; padding-left: 18px; color: #374151; font-size: 14px; line-height: 1.7;\">{items}</ul>
                  </td>
                </tr>
        """

    action_html = ""
    if safe_action_label and safe_action_url:
        action_html = f"""
                <tr>
                  <td style=\"padding-top: 24px;\">
                    <table role=\"presentation\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\">
                      <tr>
                        <td style=\"border-radius: 999px; background: {palette['accent']};\">
                          <a href=\"{safe_action_url}\" style=\"display: inline-block; padding: 12px 18px; border-radius: 999px; font-size: 14px; font-weight: 700; color: #ffffff; text-decoration: none;\">{safe_action_label}</a>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
        """

    footer_html = safe_footer or (
        "Cet email a ete genere automatiquement par AIA Studio. "
        "Si quelque chose semble incorrect, reconnecte-toi au tableau de bord."
    )

    html = f"""<!DOCTYPE html>
<html lang=\"fr\">
  <head>
    <meta charset=\"UTF-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
    <title>{safe_title}</title>
  </head>
  <body style=\"margin:0; padding:0; background:#f3f4f6; font-family: Arial, Helvetica, sans-serif; color:#111827;\">
    <table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\" style=\"background:#f3f4f6; padding:32px 16px;\">
      <tr>
        <td align=\"center\">
          <table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\" style=\"max-width:640px; background:#ffffff; border-radius:20px; overflow:hidden; box-shadow:0 12px 30px rgba(15, 23, 42, 0.08);\">
            <tr>
              <td style=\"background: linear-gradient(135deg, {palette['accent']} 0%, #111827 100%); padding: 28px 28px 24px 28px; color:#ffffff;\">
                <div style=\"font-size: 12px; letter-spacing: 0.12em; text-transform: uppercase; opacity: 0.9;\">{safe_brand}</div>
                <div style=\"margin-top: 10px; font-size: 28px; line-height: 1.2; font-weight: 800;\">{safe_title}</div>
                <div style=\"margin-top: 10px; display: inline-block; padding: 8px 12px; border-radius: 999px; background: rgba(255,255,255,0.16); font-size: 12px; font-weight: 700; letter-spacing: 0.04em;\">{escape(palette['label'])}</div>
              </td>
            </tr>
            <tr>
              <td style=\"padding: 28px;\">
                <table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\">
                  <tr>
                    <td style=\"border-left: 4px solid {palette['accent']}; background: {palette['soft']}; color: {palette['text']}; border-radius: 14px; padding: 16px 18px; font-size: 15px; line-height: 1.7; font-weight: 600;\">
                      {safe_summary}
                    </td>
                  </tr>
                </table>
                <table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\" style=\"margin-top: 20px;\">
                  {detail_cards}
                  {details_html}
                  {action_html}
                </table>
                <div style=\"margin-top: 28px; border-top: 1px solid #e5e7eb; padding-top: 16px; color:#6b7280; font-size: 12px; line-height: 1.6;\">
                  {escape(footer_html)}
                </div>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""

    text = _build_text_body(
        brand_name=brand_name,
        title=title,
        summary=summary,
        severity_label=palette["label"],
        project_name=project_name,
        project_id=project_id,
        details=normalized_details,
        action_label=action_label,
        action_url=action_url,
        footer_note=footer_note,
    )

    return AlertEmail(subject=subject, html=html, text=text)
