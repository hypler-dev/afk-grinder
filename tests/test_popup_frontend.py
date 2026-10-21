"""Actual popup component checks with synthetic state and a minimal DOM."""

import json
from pathlib import Path
import re
import subprocess
import unittest

from afk_grinder.recognition.popup_diagnostic import (
    POPUP_CAPTURE_DIAGNOSTIC_STAGES, POPUP_DIAGNOSTIC_CODES, POPUP_DIAGNOSTIC_STAGES,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "src/afk_grinder/web/app.js").read_text()


class PopupFrontendTests(unittest.TestCase):
    def test_popup_vocabularies_match_the_backend(self):
        for name, expected in (("POPUP_DIAGNOSTIC_STAGES", POPUP_DIAGNOSTIC_STAGES),
                               ("POPUP_DIAGNOSTIC_CODES", POPUP_DIAGNOSTIC_CODES),
                               ("POPUP_CAPTURE_DIAGNOSTIC_STAGES", POPUP_CAPTURE_DIAGNOSTIC_STAGES)):
            match = re.search(r"const " + name + r" = new Set\((\[[^;]+\])\);", SOURCE)
            self.assertIsNotNone(match, name)
            # Source accepts single-quoted values; JSON output below comes from
            # the actual JavaScript runtime rather than a parallel formatter.
            script = match.group(0) + f"\nconsole.log(JSON.stringify([...{name}]));"
            result = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                                    check=True, timeout=5)
            self.assertEqual(set(json.loads(result.stdout)), expected)

    def test_terminal_diagnostics_are_sanitized_quiet_and_do_not_change_controls(self):
        declarations = "\n".join(re.findall(r"const (?:CAPTURE|POPUP)_[A-Z_]+ = new Set\([^\n]+", SOURCE))
        component = SOURCE[SOURCE.index("  function popupDiagnostic("):SOURCE.index("  function replaySessions(")]
        script = r'''
const nodes = new Map(); let writes = 0;
const $ = (selector) => { if (!nodes.has(selector)) nodes.set(selector, { _text: '', hidden: true, disabled: false, checked: false,
  set textContent(value) { this._text = value; if (selector === '#popup-diagnostic') writes++; },
  get textContent() { return this._text; } }); return nodes.get(selector); };
const text = (selector, value) => { $(selector).textContent = value; };
const badge = (node, value) => { node.textContent = value; };
const phaseLabel = value => value; const model = { bridgeReady: true };
'''+declarations+"\n"+component+r'''
const session = { phase: 'idle', input_locked: false, cleanup_failed: false };
const diagnostic = { stage: 'capture', code: 'failed', capture: { code: 'permission', stage: 'preflight', error_type: 'capture_error' } };
const base = { phase: 'result', state: 'error', diagnostic, message: 'Popup check stopped.', busy: false, can_check: true, can_resolve: false, allow_reconnect: false };
renderPopup(base, session);
const row = $('#popup-diagnostic'); const original = row;
if (row.hidden || row.textContent !== 'Diagnostic: capture / failed. Capture: permission at preflight (capture_error).') throw new Error('fixed diagnostic not shown');
if ($('#popup-message').textContent !== base.message || $('#popup-check').disabled || !$('#popup-resolve').disabled) throw new Error('primary status or input gates changed');
const firstWrites = writes; renderPopup(base, session);
if (row !== original || writes !== firstWrites) throw new Error('identical poll rewrote diagnostic or replaced node');
for (const value of [
  null, [], {}, { ...diagnostic, stage: '/private/secret/chat' },
  { ...diagnostic, code: '<img onerror=secret()>' }, { ...diagnostic, extra: '/private/secret/chat' },
  { ...diagnostic, capture: { ...diagnostic.capture, error_type: '/private/secret/chat' } },
  { ...diagnostic, capture: { ...diagnostic.capture, extra: '/private/secret/chat' } },
  { ...diagnostic, capture: undefined }, { ...diagnostic, stage: 'warmup' }
]) {
  renderPopup({ ...base, diagnostic: value }, session);
  if (!row.hidden || row.textContent !== '') throw new Error('malformed diagnostic shown');
}
for (const phase of ['idle', 'checking', 'verifying']) {
  renderPopup({ ...base, phase }, session);
  if (!row.hidden || row.textContent) throw new Error('nonterminal diagnostic shown');
}
for (const state of ['unknown', 'protected', 'blocked', 'disconnected', 'bank_reward', 'popup_dismissed']) {
  renderPopup({ ...base, state }, session);
  if (!row.hidden || row.textContent) throw new Error('nonerror diagnostic shown');
}
for (const stage of POPUP_DIAGNOSTIC_STAGES) for (const code of POPUP_DIAGNOSTIC_CODES) {
  renderPopup({ ...base, diagnostic: { stage, code, capture: null } }, session);
  if (row.hidden || row.textContent !== `Diagnostic: ${stage} / ${code}.`) throw new Error('valid finite vocabulary missing');
}
renderPopup({ ...base, busy: true }, session);
if (!$('#popup-check').disabled || !$('#popup-resolve').disabled) throw new Error('busy controls enabled');
console.log('Popup diagnostic component passed; no bridge, focus, input, or live-region API exists in this harness.');
'''
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_diagnostic_row_has_no_live_region_or_focusability(self):
        from html.parser import HTMLParser
        rows = []
        class Parser(HTMLParser):
            def handle_starttag(self, tag, attrs):
                values = dict(attrs)
                if values.get("id") == "popup-diagnostic": rows.append((tag, values))
        Parser().feed((ROOT / "src/afk_grinder/web/index.html").read_text())
        self.assertEqual(len(rows), 1)
        tag, attributes = rows[0]
        self.assertEqual(tag, "p")
        self.assertIn("hidden", attributes)
        for name in ("role", "aria-live", "tabindex", "contenteditable"):
            self.assertNotIn(name, attributes)


if __name__ == "__main__":
    unittest.main()
