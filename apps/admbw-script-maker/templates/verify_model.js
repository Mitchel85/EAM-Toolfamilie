/*
 * verify_model.js — Re-Read-Verifikation nach jedem Write.
 *
 * Review-Fix 19.10.2026 (AAroN-Abgleich, schmitze87/AAroN):
 *  - Soll/Ist-Abgleich statt reiner Ist-Zählung (EXPECTED aus dem IR setzen!)
 *  - Duplikat-GUIDs über t_object UND t_connector (EAObject.EA_GUID,
 *    EAConnector.EA_GUID in AAroN)
 *  - SQLQuery-Ergebnisparser: EA liefert XML <Row><ALIAS>wert</ALIAS></Row>;
 *    kein "-1-"-Trenner, kein CLASSGUID-Zwang, kein <Value>-Knoten.
 *  - "Realization" und "Realisation" werden beide geprüft.
 *
 * Ausfuehrung: EA-Scripting-Fenster (JavaScript).
 */

/* ── SOLLWERTE AUS DEM IR EINTRAGEN ───────────────────────────────────────
 * null = kein Sollwert vorhanden (wird als WARNUNG, nicht als PASS gemeldet).
 * 0    = ausdrücklicher Sollwert 0 (z. B. „keine ungültigen Endpunkte“).
 * stereotypes: exakte Stereotyp-Namen aus dem IR und deren Anzahl.
 */
var EXPECTED = {
    elements: null,
    connectors: null,
    diagrams: null,
    stereotypes: {
        // "Capability": 3,
        // "OperationalActivity": 2,
        // "ServiceSpecification": 1
    }
};

var VERIFY = { fails: 0, checks: 0 };

function log(msg) { Session.Output(msg); }

function fail(msg) {
    VERIFY.fails++;
    log("!!  " + msg);
}

function ok(msg) {
    log("OK  " + msg);
}

function sqlNumber(sql, label) {
    var res;
    try {
        res = Repository.SQLQuery(sql);
    } catch (e) {
        fail(label + ": SQLQuery-Fehler: " + e.message);
        return -1;
    }
    if (res === null || res === undefined || res === "") {
        fail(label + ": leeres SQLQuery-Ergebnis");
        return -1;
    }
    /* EA-Format: <EADATA><Dataset><Data><Row><ALIAS>123</ALIAS></Row>...
       Der erste numerische Wert im ersten Row-Block ist die Antwort. */
    var m = String(res).match(/<([A-Za-z0-9_]+)>\s*(-?\d+)\s*<\/\1>/);
    if (m) return parseInt(m[2], 10);
    /* Fallback: reine Zahl (falls der Treiber bereits skalar liefert) — nur
       wenn der String KEINE XML-Tags enthält (sonst Fehler-/leeres Dokument). */
    var s = String(res);
    if (s.indexOf('<') === -1) {
        var n = s.replace(/[^0-9-]/g, "");
        if (n !== "" && !isNaN(parseInt(n, 10))) return parseInt(n, 10);
    }
    fail(label + ": Ergebnis nicht als Zahl lesbar: " + String(res).substring(0, 160));
    return -1;
}

function checkCount(label, actual, expected) {
    VERIFY.checks++;
    if (actual < 0) return; /* sqlNumber hat bereits FAIL gemeldet */
    if (expected === null || expected === undefined) {
        log("--  " + label + ": " + actual + " (kein Sollwert gesetzt)");
    } else if (actual === expected) {
        ok(label + ": " + actual + " (Soll " + expected + ")");
    } else {
        fail(label + ": IST " + actual + " / SOLL " + expected);
    }
}

function main() {
    log("=== VERIFY START ===");

    /* 1) Gesamtzahlen (Paket-Elemente zählen nicht als Modell-Elemente:
       EA legt für jedes Paket ein t_object vom Typ 'Package' an) */
    checkCount("Elemente gesamt",
        sqlNumber("SELECT COUNT(*) AS C FROM t_object WHERE Object_Type <> 'Package'", "Elemente gesamt"),
        EXPECTED.elements);
    checkCount("Connectors gesamt",
        sqlNumber("SELECT COUNT(*) AS C FROM t_connector", "Connectors gesamt"),
        EXPECTED.connectors);
    checkCount("Diagramme gesamt",
        sqlNumber("SELECT COUNT(*) AS C FROM t_diagram", "Diagramme gesamt"),
        EXPECTED.diagrams);

    /* 2) Elemente je Stereotyp (nur wenn Sollwert gesetzt) */
    for (var s in EXPECTED.stereotypes) {
        if (!EXPECTED.stereotypes.hasOwnProperty(s)) continue;
        checkCount("Elemente «" + s + "»",
            sqlNumber("SELECT COUNT(*) AS C FROM t_object WHERE Stereotype = '" + s.replace(/'/g, "''") + "' AND Object_Type <> 'Package'",
                "Elemente «" + s + "»"),
            EXPECTED.stereotypes[s]);
    }

    /* 3) Connector-Typen: Ist-Zählung; Realization/Realisation beide prüfen */
    var conTypes = ["Generalization", "Dependency", "Association", "Abstraction", "Realization", "Realisation", "InformationFlow"];
    for (var i = 0; i < conTypes.length; i++) {
        var ct = conTypes[i];
        log("--  Connectors " + ct + ": " + sqlNumber(
            "SELECT COUNT(*) AS C FROM t_connector WHERE Connector_Type = '" + ct + "'",
            "Connectors " + ct));
    }

    /* 4) Referenzintegrität: SOLL 0 */
    checkCount("Connectors mit ungültigen Endpunkten (SOLL 0)",
        sqlNumber("SELECT COUNT(*) AS C FROM t_connector WHERE Start_Object_ID NOT IN (SELECT Object_ID FROM t_object) OR End_Object_ID NOT IN (SELECT Object_ID FROM t_object)",
            "Ungültige Connector-Endpunkte"),
        0);

    /* 5) Duplikat-GUIDs: t_object UND t_connector, SOLL 0 */
    checkCount("Doppelte Element-GUIDs (SOLL 0)",
        sqlNumber("SELECT COUNT(*) AS C FROM (SELECT ea_guid FROM t_object GROUP BY ea_guid HAVING COUNT(*) > 1) AS DupObj",
            "Doppelte Element-GUIDs"),
        0);
    checkCount("Doppelte Connector-GUIDs (SOLL 0)",
        sqlNumber("SELECT COUNT(*) AS C FROM (SELECT ea_guid FROM t_connector GROUP BY ea_guid HAVING COUNT(*) > 1) AS DupCon",
            "Doppelte Connector-GUIDs"),
        0);

    log("--- VERIFY REPORT ---");
    log("Prüfungen: " + VERIFY.checks + " · Fehler: " + VERIFY.fails);
    if (VERIFY.fails > 0) log("VERIFY: FAIL");
    else log("VERIFY: PASS (nur geprüfte Sollwerte; nicht gesetzte Werte sind keine Bestätigung)");
    log("=== VERIFY ENDE ===");
}

main();
