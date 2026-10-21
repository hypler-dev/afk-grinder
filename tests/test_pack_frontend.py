"""Synthetic DOM checks for the local read-only recognition-pack controls."""

from pathlib import Path
import subprocess
import tempfile
import unittest


APP = Path(__file__).resolve().parents[1] / "src/afk_grinder/web/app.js"


class PackFrontendTests(unittest.TestCase):
    def test_pack_bridge_gates_metadata_and_current_preview_guards(self) -> None:
        script = r'''
const fs = require('fs');
const strokes = []; const pendingImages = [];
class Node {
  constructor() { this.children = []; this.dataset = {}; this.className = ''; this.hidden = false; this.disabled = false; this.value = ''; this.checked = false; this.style = {}; this.parentElement = { clientWidth: 800 }; this.clientWidth = 800; this.classList = { toggle() {} }; this._text = ''; }
  set textContent(value) { this._text = value; this.children = []; }
  get textContent() { return this._text; }
  get content() { return { firstElementChild: this }; }
  cloneNode() { return new Node(); }
  querySelector() { return new Node(); }
  append(...items) { for (const item of items) { item.parentElement = this; this.children.push(item); } }
  addEventListener(name, fn) { this.listeners ||= {}; this.listeners[name] = fn; }
  fire(name) { if (this.listeners && this.listeners[name]) this.listeners[name]({ target: this, preventDefault() {} }); }
  setAttribute() {} removeAttribute() {} toggleAttribute() {} remove() {}
  getContext() { return { setTransform() {}, clearRect() {}, drawImage() {}, fillRect() {}, strokeRect(...args) { strokes.push(args); } }; }
}
const ids = new Map(); const id = (name) => { if (!ids.has(name)) ids.set(name, new Node()); return ids.get(name); };
const recording = ['#recording-enabled','#recording-days','#recording-format','#recording-width','#recording-quality','#recording-interval','#recording-cap'].map(id);
global.document = { visibilityState: 'hidden', activeElement: null, querySelector: id, querySelectorAll(selector) { return selector.startsWith('#recording-') ? recording : []; }, createElement() { return new Node(); }, addEventListener() {} };
global.window = { setTimeout, clearTimeout, setInterval, clearInterval, addEventListener() {}, pywebview: { api: {} } };
global.Image = class { set src(value) { this.value = value; pendingImages.push(this); } };
const commands = []; window.pywebview.api.command = async (name, payload) => { commands.push({name, payload}); return { ok: true }; };
let source = fs.readFileSync(process.argv[1], 'utf8').replace(/\r\n?/g, '\n');
const startup = "  route('library'); render(); poll(); window.setInterval(poll, POLL_MS);\n})();";
if (!source.includes(startup)) throw new Error('pack harness startup anchor is missing');
source = source.replace(startup, "  globalThis.__packTest = { model, render, applyState, normalizePackInspection, redrawPreviews };\n})();");
eval(source);
const ui = globalThis.__packTest;
ui.render(); // Real startup renders once before the first bridge response.
if (!id('#pack-choose').disabled || !id('#pack-check').disabled || !id('#pack-clear').disabled) throw new Error('initial disconnected controls stayed enabled');
const inspection = { status: 'known', state_id: '<state>', kind: 'gameplay', reason: 'fresh', stable_count: 2, required_frames: 3, historical: true, preview_id: 8, width: 100, height: 50, anchors: [{ id: '<anchor>', score: .8, box: { x: 4, y: 5, width: 10, height: 12 } }, { id: 'bad-box', score: Infinity, box: { x: -1, y: 0, width: 10, height: 12 } }] };
const state = (preview = { id: 8, width: 100, height: 50, phase: 'available', geometry: 'matched' }, pack = {}) => ({ game_id: 'adopt', games: [], mode: 'dry', session: { phase: 'idle', message: '', can_start: false, acknowledged: false, input_locked: false, cleanup_failed: false }, preview, binding: { target_id: 'target-a' }, readiness: {}, app: {}, template: {}, popup: {}, replay: {}, pack: { phase: 'result', id: '<pack>', version: '1.0', source: '<source>', message: '<message>', read_only: true, busy: false, can_choose: true, can_check: true, can_clear: true, inspection, ...pack } });
ui.model.bridgeReady = true;
ui.applyState(state());
if (id('#pack-id').textContent !== '<pack>' || id('#pack-source').textContent !== '<source>' || id('#pack-message').textContent !== '<message>') throw new Error('pack values were not rendered as text');
if (!id('#pack-inspection-phase').textContent.includes('Visual state seen') || !id('#pack-inspection-detail').textContent.includes('Historical') || !id('#pack-stability').textContent.includes('2 of 3')) throw new Error('known historical inspection was not labelled');
id('#pack-choose').fire('click'); id('#pack-check').fire('click'); id('#pack-clear').fire('click');
if (JSON.stringify(commands) !== JSON.stringify([{name:'pack_choose',payload:{}},{name:'pack_check',payload:{}},{name:'pack_clear',payload:{}}])) throw new Error(JSON.stringify(commands));
ui.model.image = 'data:image/png;base64,QQ=='; ui.model.imageId = 8; ui.model.previewGameId = 'adopt'; ui.applyState(state());
const image = pendingImages.shift(); image.naturalWidth = 100; image.naturalHeight = 50; image.onload();
if (strokes.length !== 1 || id('#pack-anchor-list').children.length !== 2 || !id('#pack-anchor-list').children[0].textContent.includes('<anchor>') || !id('#pack-anchor-list').children[1].textContent.includes('no score')) throw new Error('anchor metadata was not safely normalized');
ui.applyState(state({ id: 9, width: 100, height: 50, phase: 'available', geometry: 'matched' }));
if (!id('#pack-canvas').hidden || id('#pack-empty').hidden) throw new Error('old preview inspection remained drawable');
if (pendingImages.length) { const stale = pendingImages.shift(); stale.naturalWidth = 100; stale.naturalHeight = 50; stale.onload(); }
if (strokes.length !== 1) throw new Error('stale async image drew an overlay');
const largeInspection = { ...inspection, preview_id: 8, width: 943, height: 632, anchors: [{ id: 'large', score: .9, box: { x: 100, y: 50, width: 20, height: 20 } }] };
ui.model.image = 'data:image/png;base64,Qg=='; ui.model.imageId = 8; ui.model.previewGameId = 'adopt'; ui.applyState(state({ id: 8, width: 943, height: 632, phase: 'available', geometry: 'matched' }, { inspection: largeInspection }));
let encoded = pendingImages.shift(); encoded.naturalWidth = 470; encoded.naturalHeight = 316; encoded.onload();
if (strokes.length !== 1 || !id('#pack-canvas').hidden) throw new Error('wrong encoded dimensions drew an overlay');
pendingImages.length = 0;
ui.model.packCanvasKey = ''; ui.redrawPreviews(); encoded = pendingImages.pop(); encoded.naturalWidth = 471; encoded.naturalHeight = 316; encoded.onload();
if (strokes.length !== 2 || id('#pack-canvas').hidden) throw new Error('expected encoded dimensions were rejected');
const largeStroke = strokes[1][0]; pendingImages.length = 0; ui.model.packCanvasKey = ''; ui.redrawPreviews(); encoded = pendingImages.pop(); ui.model.imageId = 9; encoded.naturalWidth = 471; encoded.naturalHeight = 316; encoded.onload();
if (strokes.length !== 2) throw new Error('wrong preview ID drew an overlay');
ui.model.imageId = 8; pendingImages.length = 0; id('#pack-canvas').parentElement.clientWidth = 400; ui.redrawPreviews(); encoded = pendingImages.pop(); encoded.naturalWidth = 471; encoded.naturalHeight = 316; encoded.onload();
if (strokes.length !== 3 || strokes[2][0] >= largeStroke) throw new Error('resize did not redraw raw-coordinate overlay alignment');
ui.applyState(state(undefined, { phase: 'checking', busy: true, can_choose: true, can_check: true, can_clear: true }));
if (!id('#pack-choose').disabled || !id('#pack-check').disabled || !id('#pack-clear').disabled) throw new Error('busy pack controls stayed enabled');
if (ui.normalizePackInspection(state(undefined, { inspection: { ...inspection, preview_id: 7 } })) !== null) throw new Error('mismatched preview inspection was accepted');
'''
        source = APP.read_bytes().replace(b"\r\n", b"\n")
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "app.js"
            fixture.write_bytes(source)
            result = subprocess.run(["node", "-e", script, str(fixture)], capture_output=True,
                                    text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
