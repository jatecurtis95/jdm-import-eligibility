"""Render email-template-v2.html with sample data so it can be opened in a browser.

Mirrors the production helpers in rover_scraper.py — when those change, this
file should be updated in tandem so what you preview is what you ship.
"""
import re
from pathlib import Path

HERE = Path(__file__).parent
src = (HERE / "email-template.html").read_text(encoding="utf-8")

replacements = {
    "{{PREHEADER_TEXT}}": "Skyline V-Spec II Nur now eligible (+3 more)",
    "{{WEEK_DATE}}": "13 May 2026",
    "{{DATA_REFRESHED}}": "13 May 2026 at 21:23 AWST",
    "{{MONTHLY_TREND}}": ' <span style="color:#6b7280;">&middot;</span> <span style="color:#9ca3af;">+12 vs last month</span>',
    "{{ADDED_COUNT}}": "4",
    "{{REMOVED_COUNT}}": "1",
    "{{EXPIRING_COUNT}}": "23",
    "{{NEXT_UPDATE}}": "20 May 2026",
    "{{UNSUBSCRIBE_URL}}": "mailto:info@jdmconnect.com.au?subject=Unsubscribe",
    "{{REGISTER_TOTALS}}": (
        'Register stands at <span style="color:#e8eaea; font-family:\'JetBrains Mono\',Menlo,Consolas,monospace;">1,502</span> entries '
        '<span style="color:#4ade80;">(+3)</span> &middot; '
        '<span style="color:#9ca3af;">608 SEVS &middot; 894 MRE</span>'
    ),
}

# Open IF blocks, drop NO_CHANGES
for tag in ("ADDED", "REMOVED", "EXPIRING", "HEADLINES"):
    src = src.replace("{{#IF_" + tag + "}}", "").replace("{{/IF_" + tag + "}}", "")
src = re.sub(r"\{\{#IF_NO_CHANGES\}\}.*?\{\{/IF_NO_CHANGES\}\}", "", src, flags=re.DOTALL)


# --- Vehicle rows (mirrors current Python output) ---
def vehicle_row(name, register_type, ref, secondary, badge_bg, badge_color, badge_border, badge_cls, subtitle):
    link_color = "#60a5fa" if register_type == "MRE" else "#4ade80"
    site = "https://eligibility.jdmconnect.com.au"
    sub_html = ""
    if subtitle:
        sub_html = '<div style="font-size:12px; color:#9ca3af; margin-top:4px; line-height:1.5;">' + subtitle + "</div>"
    cta = ('<div style="margin-top:8px;"><a href="mailto:info@jdmconnect.com.au?subject=Quote%20' + name.replace(" ", "%20")
           + '" style="font-family:\'Inter\',sans-serif; font-size:12px; font-weight:600; color:#C9A84C; text-decoration:none; letter-spacing:0.3px;">Get a quote &rarr;</a></div>')
    return (
        '<tr><td style="padding:16px 0; border-bottom:1px solid #2e2820;">'
        '<div style="font-family:\'Inter\',sans-serif; font-size:15px; font-weight:600; color:#e8eaea; line-height:1.3;">' + name + "</div>"
        + sub_html + cta +
        '</td>'
        '<td style="padding:16px 0; border-bottom:1px solid #2e2820; vertical-align:top; width:80px;" align="right">'
        '<span style="display:inline-block; padding:3px 10px; border-radius:20px; font-family:\'Inter\',sans-serif; font-size:11px; font-weight:600; background-color:'
        + badge_bg + "; color:" + badge_color + "; border:1px solid " + badge_border + ';" class="' + badge_cls + '">' + register_type + "</span>"
        '</td>'
        '<td style="padding:16px 0 16px 16px; border-bottom:1px solid #2e2820; font-family:\'Inter\',sans-serif; font-size:13px; color:#9ca3af; line-height:1.5; vertical-align:top; width:170px;" class="detail-col">'
        '<a href="' + site + '" style="color:' + link_color + '; text-decoration:none; font-weight:600; font-family:\'JetBrains Mono\',\'Menlo\',\'Consolas\',monospace; font-size:12px;">#' + ref + "</a><br>"
        '<span style="color:#6b7280; font-size:12px;">' + secondary + "</span>"
        "</td></tr>"
    )


added_rows = "\n".join([
    vehicle_row("Nissan Skyline GT-R V-Spec II Nur", "SEVS", "SEV-000851", "BNR34 - 02/2002 to 08/2002",
                "#0d2618", "#4ade80", "#2d8a4f", "badge-sevs", "Performance Enthusiast &middot; Expires 13 May 31"),
    vehicle_row("Toyota Sienta", "SEVS", "SEV-000850", "NCP80 - 09/2003 to 06/2015",
                "#0d2618", "#4ade80", "#2d8a4f", "badge-sevs", "Welcab / Mobility &middot; Expires 10 Apr 28"),
    vehicle_row("RAM 2500", "MRE", "MRE-000942", "8/2018 to current",
                "#0d1a2e", "#60a5fa", "#1e3a5f", "badge-mre", "Workshop: Apex Auto"),
    vehicle_row("Toyota Pixis Truck", "MRE", "MRE-000943", "12/2021 to 2/2025",
                "#0d1a2e", "#60a5fa", "#1e3a5f", "badge-mre", "Workshop: Hino Compliance"),
])
src = re.sub(r"\{\{#EACH_ADDED\}\}.*?\{\{/EACH_ADDED\}\}", added_rows, src, flags=re.DOTALL)

# Removed
removed_rows = (
    '<tr><td style="padding:16px 0; border-bottom:1px solid #2e2820;">'
    '<div style="font-family:\'Inter\',sans-serif; font-size:15px; font-weight:600; color:#9ca3af; text-decoration:line-through; line-height:1.3;">Honda S660</div>'
    '<div style="font-size:12px; color:#9ca3af; margin-top:4px; line-height:1.5;">Approval expired &middot; '
    '<span style="font-family:\'JetBrains Mono\',\'Menlo\',\'Consolas\',monospace;">JW5</span></div>'
    '</td>'
    '<td style="padding:16px 0; border-bottom:1px solid #2e2820; vertical-align:top; width:80px;" align="right">'
    '<span style="display:inline-block; padding:3px 10px; border-radius:20px; font-family:\'Inter\',sans-serif; font-size:11px; font-weight:600; '
    'background-color:#252b33; color:#9ca3af; border:1px solid #3d4550;" class="badge-gray">Removed</span>'
    '</td>'
    '<td style="padding:16px 0 16px 16px; border-bottom:1px solid #2e2820; font-family:\'Inter\',sans-serif; font-size:13px; color:#9ca3af; line-height:1.5; vertical-align:top; width:170px;" class="detail-col">'
    '<a href="#" style="color:#9ca3af; text-decoration:none; font-family:\'JetBrains Mono\',\'Menlo\',\'Consolas\',monospace; font-size:12px;">#SEV-000412</a><br>'
    '<span style="color:#6b7280; font-size:12px;">04/2015 to 03/2022</span>'
    '</td></tr>'
)
src = re.sub(r"\{\{#EACH_REMOVED\}\}.*?\{\{/EACH_REMOVED\}\}", removed_rows, src, flags=re.DOTALL)


# --- Expiring rows — banded by urgency (mirrors _build_expiring_rows) ---
def band_header(label, color, sublabel):
    return (
        '<tr><td style="padding:22px 0 12px;">'
        '<div style="font-family:\'Inter\',sans-serif; font-size:10px; color:' + color +
        '; letter-spacing:3px; text-transform:uppercase; font-weight:700;">' + sublabel + '</div>'
        '<div style="font-family:\'Playfair Display\',Georgia,serif; font-size:17px; '
        'color:#e8eaea; line-height:1.3; font-style:italic; margin-top:4px;">' + label + '</div>'
        '</td></tr>'
    )


def expiring_row(name, ref, model_code, expires, days):
    if days <= 7:
        day_color = "#f87171"
    elif days <= 14:
        day_color = "#C9A84C"
    else:
        day_color = "#9ca3af"
    meta = (
        '<a href="#" style="color:#9ca3af; text-decoration:none; font-family:\'JetBrains Mono\',Menlo,Consolas,monospace; font-size:12px;">SEV #' + ref + '</a>'
        ' &middot; <span style="font-family:\'JetBrains Mono\',Menlo,Consolas,monospace; color:#6b7280; font-size:12px;">' + model_code + '</span>'
        ' &middot; <span style="color:#6b7280; font-size:12px;">Expires ' + expires + '</span>'
    )
    return (
        '<tr><td style="padding:14px 0; border-bottom:1px solid #2e2820;">'
        '<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%"><tr>'
        '<td style="vertical-align:middle;">'
        '<div style="font-family:\'Inter\',sans-serif; font-size:15px; font-weight:600; color:#e8eaea; line-height:1.3;">' + name + '</div>'
        '<div style="margin-top:4px; line-height:1.5;">' + meta + '</div>'
        '</td>'
        '<td align="right" valign="middle" style="vertical-align:middle; width:80px;">'
        '<div style="font-family:\'JetBrains Mono\',Menlo,Consolas,monospace; font-size:22px; font-weight:600; color:' + day_color + '; line-height:1; letter-spacing:-0.5px;">' + str(days) + '</div>'
        '<div style="font-family:\'Inter\',sans-serif; font-size:9px; color:#6b7280; letter-spacing:2px; text-transform:uppercase; margin-top:4px;">Days</div>'
        '</td></tr></table></td></tr>'
    )


# Critical / warning / notice samples — totals 23 across all bands.
critical = [
    ("Mazda RX-7 Spirit R", "000201", "FD3S", "21 May 26", 8),
    ("Mitsubishi Lancer Evolution VI TME", "000189", "CP9A", "19 May 26", 6),
]
warning = [
    ("Subaru Impreza WRX STI 22B", "000234", "GC8", "27 May 26", 14),
    ("Toyota Chaser Tourer V", "000245", "JZX100", "23 May 26", 10),
    ("Nissan Stagea 260RS", "000252", "WGNC34", "26 May 26", 13),
]
notice_rows = [
    ("Toyota Supra RZ", "000277", "JZA80", "9 Jun 26", 27),
    ("Honda Integra Type R", "000281", "DC2", "5 Jun 26", 23),
    ("Mazda RX-8 Type S", "000288", "SE3P", "11 Jun 26", 29),
]

bands_html = []
if critical:
    bands_html.append(band_header(
        "Act this week.", "#f87171",
        "Under 7 days &middot; " + str(len(critical)) + (" approval" if len(critical) == 1 else " approvals")))
    bands_html.extend(expiring_row(*r) for r in critical)
if warning:
    bands_html.append(band_header(
        "Heads up.", "#C9A84C",
        "8 to 14 days &middot; " + str(len(warning)) + (" approval" if len(warning) == 1 else " approvals")))
    bands_html.extend(expiring_row(*r) for r in warning)
if notice_rows:
    bands_html.append(band_header(
        "On the radar.", "#9ca3af",
        "15 to 30 days &middot; " + str(len(notice_rows)) + (" approval" if len(notice_rows) == 1 else " approvals")))
    bands_html.extend(expiring_row(*r) for r in notice_rows)

expiring_html = "\n".join(bands_html)
src = re.sub(r"\{\{#EACH_EXPIRING\}\}.*?\{\{/EACH_EXPIRING\}\}", expiring_html, src, flags=re.DOTALL)

# Headlines
headline_rows = (
    '<tr><td style="padding:16px 0; border-bottom:1px solid #2e2820;">'
    '<a href="#" target="_blank" style="font-family:\'Playfair Display\',Georgia,serif; font-size:17px; font-weight:600; color:#e8eaea; text-decoration:none; line-height:1.3; display:block;">'
    "DITRDCA opens consultation on personal import scheme reforms</a>"
    '<p style="margin:6px 0 0; font-family:\'Inter\',sans-serif; font-size:13px; color:#9ca3af; line-height:1.55;">Submissions open until 30 June 2026. Affects SEVS pathway eligibility for 25-year-rule vehicles.</p>'
    '<div style="margin-top:8px; font-family:\'Inter\',sans-serif; font-size:10px; color:#6b7280; letter-spacing:2px; text-transform:uppercase; font-weight:600;">ATO</div>'
    '</td></tr>'
)
src = re.sub(r"\{\{#EACH_HEADLINE\}\}.*?\{\{/EACH_HEADLINE\}\}", headline_rows, src, flags=re.DOTALL)

for k, v in replacements.items():
    src = src.replace(k, v)

out = HERE / "email-template-v2-preview.html"
out.write_text(src, encoding="utf-8")
print("Wrote " + str(out) + " (" + str(len(src)) + " chars)")
