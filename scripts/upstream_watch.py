#!/usr/bin/env python3
"""Prüft amtliche Quellen (Bundeswehr/BAAINBw & NATO) auf neue Leitfäden, MDGs und NAFv4-Versionen.

Reiner Benachrichtigungs-Wächter (Ping-Modus): ändert niemals Dateien, Branches oder Commits.

    python3 scripts/upstream_watch.py [--letzter-snapshot pfad.txt] [--bericht ping.md]

Exit-Codes:
    0  Keine ungemeldeten Änderungen (Stand aktuell oder bereits gepingt).
    2  Neue oder geänderte Dokumente erkannt (Ping-Bericht geschrieben).
    1  Keine der Quellen war erreichbar.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FETCH = ROOT / "scripts" / "fetch_quellen.py"

UA = "Mozilla/5.0 (compatible; EAM-Toolfamilie-Upstream-Watch/1.0)"

BW_SEITE = (
    "https://www.bundeswehr.de/de/organisation/ausruestung-baainbw/"
    "vergabe/methode-architektur"
)
BW_BASIS = "https://www.bundeswehr.de/resource/blob/"

NATO_SEITE = (
    "https://www.nato.int/en/about-us/organization/nato-structure/"
    "digital-policy-committee-dpc/nato-architecture-framework-version"
)
NATO_HOST = "https://www.nato.int"

#: Bekannter Ausgangsstand der NATO-NAFv4.1-Seite (erfasst 2026-11-21).
#: Bei neuer Datei oder geändertem ETag / Content-Length meldet der Wächter den Ping.
NATO_BASELINE: dict[str, dict[str, str]] = {
    "/content/dam/nato/webready/documents/publications-and-reports/20190404_AC_322-N-201-0046_ENG-UAF-Guidelines1.pdf": {
        "etag": '"0x8DD988E6D6979F1"',
        "last_modified": "Wed, 21 May 2025 17:39:24 GMT",
        "content_length": "2947837",
    },
    "/content/dam/nato/webready/documents/publications-and-reports/NATO-Architecture-Framework-ArchiMate-v4-1-en.pdf": {
        "etag": '"0x8DED5B5C3C97600"',
        "last_modified": "Mon, 29 Jun 2026 08:09:38 GMT",
        "content_length": "5069750",
    },
    "/content/dam/nato/webready/documents/publications-and-reports/NATO-Architecture-Framework-v4-1-cover-en.pdf": {
        "etag": '"0x8DE836F0EF922B1"',
        "last_modified": "Mon, 16 Mar 2026 15:16:54 GMT",
        "content_length": "3402431",
    },
    "/content/dam/nato/webready/documents/publications-and-reports/NATO-Architecture-Framework-v4-1-en.pdf": {
        "etag": '"0x8DE836F1097D820"',
        "last_modified": "Mon, 16 Mar 2026 15:16:57 GMT",
        "content_length": "4983885",
    },
}

BLOB_RE = re.compile(r'resource/blob/\d+/[a-f0-9]+/[^"\'?\s]+')
TUPEL_RE = re.compile(r'\("([^"]+)",\s*"([^"]+)"\)')
NATO_DOC_RE = re.compile(
    r'href=["\']([^"\']+\.(?:pdf|zip|docx?|xlsx?|xml|7z)(?:\?[^"\']*)?)["\']',
    re.IGNORECASE,
)
SNAPSHOT_RE = re.compile(r"<!--\s*UPSTREAM_SNAPSHOT_JSON:(\{.*?\})\s*-->", re.DOTALL)


def _lade_text(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        roh = resp.read()
        if roh[:2] == b"\x1f\x8b":
            roh = gzip.decompress(roh)
        return roh.decode("utf-8", "replace")


def _head_meta(url: str, timeout: int = 20) -> dict[str, str]:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return {
                "etag": (resp.headers.get("ETag") or "").strip(),
                "last_modified": (resp.headers.get("Last-Modified") or "").strip(),
                "content_length": (resp.headers.get("Content-Length") or "").strip(),
            }
    except (OSError, urllib.error.URLError):
        return {"etag": "", "last_modified": "", "content_length": ""}


def finde_bw_blobs(html_text: str) -> dict[str, str]:
    """Ressourcenname -> Blob-Pfad (ohne `resource/blob/`-Präfix)."""
    gefunden: dict[str, str] = {}
    for pfad in BLOB_RE.findall(html_text):
        pfad = pfad.removeprefix("resource/blob/")
        name = pfad.rsplit("/", 1)[-1]
        gefunden[name] = pfad
    return dict(sorted(gefunden.items()))


def bw_baseline_aus_fetch(fetch_path: Path = FETCH) -> dict[str, str]:
    """Liest die bekannten BAAINBw-Blobs aus `scripts/fetch_quellen.py`."""
    text = fetch_path.read_text(encoding="utf-8")
    anfang = text.index("DATEIEN = [")
    ende = text.index("]", anfang)
    out: dict[str, str] = {}
    for _lokal, pfad in TUPEL_RE.findall(text[anfang:ende]):
        name = pfad.rsplit("/", 1)[-1]
        out[name] = pfad
    return dict(sorted(out.items()))


def ist_mdg(ressourcename: str) -> bool:
    n = ressourcename.lower()
    return "mdg" in n and n.endswith(".zip")


def finde_nato_links(html_text: str) -> list[str]:
    """Extrahiert alle Dokument-Links (PDF/ZIP/DOCX/XML/7z) der NATO-NAFv4-Seite."""
    gefunden: set[str] = set()
    for href in NATO_DOC_RE.findall(html_text):
        sauber = href.split("?", 1)[0].strip()
        if sauber.startswith(NATO_HOST):
            sauber = sauber.removeprefix(NATO_HOST)
        if sauber:
            gefunden.add(sauber)
    return sorted(gefunden)


def nato_url(pfad: str) -> str:
    if pfad.startswith(("http://", "https://")):
        return pfad
    return urllib.parse.urljoin(NATO_HOST, pfad)


def lade_nato_stand(html_text: str, *, head_fn=_head_meta) -> dict[str, dict[str, str]]:
    stand: dict[str, dict[str, str]] = {}
    for pfad in finde_nato_links(html_text):
        stand[pfad] = head_fn(nato_url(pfad))
    return stand


def extrahiere_snapshot(text: str) -> dict[str, Any]:
    """Liest den zuletzt gemeldeten Snapshot aus einem Issue-Body oder JSON."""
    if not text.strip():
        return {}
    treffer = SNAPSHOT_RE.search(text)
    if treffer:
        try:
            daten = json.loads(treffer.group(1))
            if isinstance(daten, dict):
                return daten
        except json.JSONDecodeError:
            return {}
    try:
        daten = json.loads(text)
        if isinstance(daten, dict):
            return daten
    except json.JSONDecodeError:
        pass
    return {}


def vergleiche_bw(
    aktuell: dict[str, str], referenz: dict[str, str]
) -> dict[str, Any]:
    geaendert: dict[str, tuple[str, str]] = {}
    neu: dict[str, str] = {}
    entfernt: dict[str, str] = {}
    for name, pfad in sorted(aktuell.items()):
        if name not in referenz:
            neu[name] = pfad
        elif referenz[name] != pfad:
            geaendert[name] = (referenz[name], pfad)
    for name, pfad in sorted(referenz.items()):
        if name not in aktuell:
            entfernt[name] = pfad
    mdg_neu = any(ist_mdg(n) for n in list(geaendert) + list(neu))
    return {
        "geaendert": geaendert,
        "neu": neu,
        "entfernt": entfernt,
        "mdg_geaendert": mdg_neu,
        "hat_aenderung": bool(geaendert or neu or entfernt),
    }


def _nato_meta_gleich(alt: dict[str, str], neu: dict[str, str]) -> bool:
    alt_etag, neu_etag = alt.get("etag", ""), neu.get("etag", "")
    if alt_etag and neu_etag:
        return alt_etag == neu_etag
    alt_len, neu_len = alt.get("content_length", ""), neu.get("content_length", "")
    if alt_len and neu_len:
        return alt_len == neu_len
    alt_mod, neu_mod = alt.get("last_modified", ""), neu.get("last_modified", "")
    if alt_mod and neu_mod:
        return alt_mod == neu_mod
    return True


def vergleiche_nato(
    aktuell: dict[str, dict[str, str]], referenz: dict[str, dict[str, str]]
) -> dict[str, Any]:
    geaendert: dict[str, tuple[dict[str, str], dict[str, str]]] = {}
    neu: dict[str, dict[str, str]] = {}
    entfernt: dict[str, dict[str, str]] = {}
    for pfad, meta in sorted(aktuell.items()):
        if pfad not in referenz:
            neu[pfad] = meta
        elif not _nato_meta_gleich(referenz[pfad], meta):
            geaendert[pfad] = (referenz[pfad], meta)
    for pfad, meta in sorted(referenz.items()):
        if pfad not in aktuell:
            entfernt[pfad] = meta
    return {
        "geaendert": geaendert,
        "neu": neu,
        "entfernt": entfernt,
        "hat_aenderung": bool(geaendert or neu or entfernt),
    }


def baue_bericht(
    bw_diff: dict[str, Any] | None,
    nato_diff: dict[str, Any] | None,
    snapshot: dict[str, Any],
    fehler: list[str],
    *,
    mention: str = "@Mitchel85",
    datum: str | None = None,
) -> str:
    tag = datum or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    zeilen: list[str] = [
        f"{mention} — der 3-wöchentliche Quellen-Wächter hat neue oder geänderte Dokumente erkannt (**{tag}**).",
        "",
        "> **Reiner Ping-Modus:** Am Repository wurden **keine** Dateien, Branches oder Commits geändert.",
        "",
    ]

    if bw_diff and bw_diff["hat_aenderung"]:
        zeilen.append("## Bundeswehr / BAAINBw (Methode Architektur — ADMBw / MDG / Leitfäden)")
        zeilen.append(f"Quelle: {BW_SEITE}")
        zeilen.append("")
        for name, (_alt, neu_pfad) in bw_diff["geaendert"].items():
            mark = " **(MDG!)**" if ist_mdg(name) else ""
            zeilen.append(f"- **Geändert{mark}:** [`{name}`]({BW_BASIS}{neu_pfad})")
        for name, neu_pfad in bw_diff["neu"].items():
            mark = " **(MDG!)**" if ist_mdg(name) else ""
            zeilen.append(f"- **Neu hochgeladen{mark}:** [`{name}`]({BW_BASIS}{neu_pfad})")
        for name, _alt_pfad in bw_diff["entfernt"].items():
            zeilen.append(f"- **Nicht mehr verlinkt:** `{name}`")
        zeilen.append("")
        if bw_diff["mdg_geaendert"]:
            zeilen.extend(
                [
                    "### Optional: Automatischer Umbau für die neue ADMBw-MDG",
                    "Wenn du die neue MDG automatisch übernehmen willst (XML entpacken, PII neutralisieren, `CURRENT` setzen, `propagate.py` baut Wissensbasis & HTML-Daten um → PR `rules/auto-update`):",
                    "- **1-Klick in GitHub Actions:** *Actions → `regelwerk-waechter` → Run workflow → Modus **`mdg-uebernehmen`** *",
                    "- **Oder lokal:** `python3 scripts/regelwerk_update.py --uebernehmen`",
                    "",
                ]
            )

    if nato_diff and nato_diff["hat_aenderung"]:
        zeilen.append("## NATO (NAFv4 / NAFv4.1 / UAF & ArchiMate Guides)")
        zeilen.append(f"Quelle: {NATO_SEITE}")
        zeilen.append("")
        for pfad, (alt_m, neu_m) in nato_diff["geaendert"].items():
            name = pfad.rsplit("/", 1)[-1]
            info = neu_m.get("last_modified") or neu_m.get("content_length") or "aktualisiert"
            alt_info = alt_m.get("last_modified") or alt_m.get("content_length") or "alt"
            zeilen.append(f"- **Geändert:** [`{name}`]({nato_url(pfad)}) ({alt_info} → {info})")
        for pfad, neu_m in nato_diff["neu"].items():
            name = pfad.rsplit("/", 1)[-1]
            info = neu_m.get("last_modified") or ""
            suffix = f" ({info})" if info else ""
            zeilen.append(f"- **Neu hochgeladen:** [`{name}`]({nato_url(pfad)}){suffix}")
        for pfad in nato_diff["entfernt"]:
            name = pfad.rsplit("/", 1)[-1]
            zeilen.append(f"- **Nicht mehr verlinkt:** `{name}`")
        zeilen.append("")
        zeilen.append("*Hinweis: NATO-Dokumente und PDF-Leitfäden werden bewusst nicht automatisch umgebaut — bitte fachlich prüfen.*")
        zeilen.append("")

    if fehler:
        zeilen.append("## Hinweise zur Erreichbarkeit")
        for f in fehler:
            zeilen.append(f"- {f}")
        zeilen.append("")

    snap_json = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    zeilen.append(f"<!-- UPSTREAM_SNAPSHOT_JSON:{snap_json} -->")
    return "\n".join(zeilen) + "\n"


def pruefe_alle(
    *,
    letzter_snapshot: dict[str, Any] | None = None,
    lade_text_fn=_lade_text,
    head_fn=_head_meta,
    fetch_path: Path = FETCH,
) -> tuple[int, str, dict[str, Any]]:
    """Prüft Bundeswehr + NATO und gibt `(exit_code, bericht_md, snapshot)` zurück."""
    alt = letzter_snapshot or {}
    bw_ref = alt.get("bw") if isinstance(alt.get("bw"), dict) else bw_baseline_aus_fetch(fetch_path)
    nato_ref = alt.get("nato") if isinstance(alt.get("nato"), dict) else dict(NATO_BASELINE)

    fehler: list[str] = []
    bw_diff: dict[str, Any] | None = None
    nato_diff: dict[str, Any] | None = None
    neuer_snapshot: dict[str, Any] = {"bw": dict(bw_ref), "nato": dict(nato_ref)}
    erfolgreich = 0

    try:
        bw_html = lade_text_fn(BW_SEITE)
        bw_aktuell = finde_bw_blobs(bw_html)
        if bw_aktuell:
            bw_diff = vergleiche_bw(bw_aktuell, bw_ref)
            neuer_snapshot["bw"] = bw_aktuell
            erfolgreich += 1
        else:
            fehler.append("Bundeswehr-Seite lieferte keine Blob-Links (HTML-Struktur evtl. geändert).")
    except (OSError, urllib.error.URLError) as exc:
        fehler.append(f"Bundeswehr-Seite nicht erreichbar: {exc}")

    try:
        nato_html = lade_text_fn(NATO_SEITE)
        nato_aktuell = lade_nato_stand(nato_html, head_fn=head_fn)
        if nato_aktuell:
            nato_diff = vergleiche_nato(nato_aktuell, nato_ref)
            neuer_snapshot["nato"] = nato_aktuell
            erfolgreich += 1
        else:
            fehler.append("NATO-Seite lieferte keine Dokument-Links (HTML-Struktur evtl. geändert).")
    except (OSError, urllib.error.URLError) as exc:
        fehler.append(f"NATO-Seite nicht erreichbar: {exc}")

    if erfolgreich == 0:
        return 1, "\n".join(fehler) + "\n", neuer_snapshot

    hat_aenderung = bool(
        (bw_diff and bw_diff["hat_aenderung"])
        or (nato_diff and nato_diff["hat_aenderung"])
    )
    if not hat_aenderung:
        return 0, "", neuer_snapshot

    bericht = baue_bericht(bw_diff, nato_diff, neuer_snapshot, fehler)
    return 2, bericht, neuer_snapshot


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Prüft Bundeswehr (ADMBw/MDG/Leitfäden) & NATO (NAFv4/NAFv4.1) — reiner Ping."
    )
    ap.add_argument(
        "--letzter-snapshot",
        type=Path,
        default=None,
        help="Datei mit letztem Issue-Body oder Snapshot-JSON zur Deduplizierung.",
    )
    ap.add_argument(
        "--bericht",
        type=Path,
        default=None,
        help="Zieldatei für den Markdown-Ping-Bericht (nur bei Exit 2 geschrieben).",
    )
    args = ap.parse_args()

    alt: dict[str, Any] = {}
    if args.letzter_snapshot and args.letzter_snapshot.is_file():
        alt = extrahiere_snapshot(args.letzter_snapshot.read_text(encoding="utf-8", errors="replace"))

    code, bericht, _snap = pruefe_alle(letzter_snapshot=alt)
    if code == 0:
        print("Keine ungemeldeten Änderungen bei Bundeswehr (ADMBw) oder NATO (NAFv4).")
        return 0
    if code == 1:
        print(bericht, file=sys.stderr, end="")
        return 1

    print(bericht, end="")
    if args.bericht:
        args.bericht.write_text(bericht, encoding="utf-8")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
