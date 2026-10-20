"""Synthetic DOM coverage for private replay UI state transitions."""

from pathlib import Path
import subprocess
import unittest


APP = Path(__file__).resolve().parents[1] / "src/afk_grinder/web/app.js"


class ReplayFrontendTests(unittest.TestCase):
    def test_replay_drafts_delete_cache_and_safe_states(self) -> None:
        script = r'''
const fs = require('fs');
class Node {
  constructor() { this.children = []; this.dataset = {}; this.className = ''; this.hidden = false; this.disabled = false; this.value = ''; this.checked = false; this.style = {}; this.parentElement = null; this.clientWidth = 800; this.classList = { toggle() {} }; }
  append(...items) { for (const item of items) { item.parentElement = this; this.children.push(item); } }
  remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter((item) => item !== this); }
  querySelector(selector) { return this.children.find((item) => selector === '.replay-cancel' && item.className.includes('replay-cancel')) || null; }
  addEventListener(name, fn) { this.listeners ||= {}; this.listeners[name] = fn; } fire(name) { if (this.listeners && this.listeners[name]) this.listeners[name]({ target: this }); } setAttribute() {} removeAttribute() {} toggleAttribute() {} getContext() { return { setTransform() {}, clearRect() {}, drawImage() {}, fillRect() {}, strokeRect() {} }; }
}
const ids = new Map();
const id = (name) => { if (!ids.has(name)) ids.set(name, new Node()); return ids.get(name); };
const recording = ['#recording-enabled','#recording-days','#recording-format','#recording-width','#recording-quality','#recording-interval','#recording-cap'].map(id);
global.document = { visibilityState: 'hidden', activeElement: null, querySelector: id, querySelectorAll(selector) { return selector.startsWith('#recording-') ? recording : []; }, createElement() { return new Node(); }, addEventListener() {} };
global.window = { setTimeout, clearTimeout, setInterval, clearInterval, addEventListener() {}, pywebview: { api: {} } };
let resolvers = [];
window.pywebview.api.get_preview = () => new Promise((resolve) => resolvers.push(resolve));
const commands = []; window.pywebview.api.command = async (name, payload) => { commands.push({name, payload}); return { ok: true }; };
let source = fs.readFileSync(process.argv[1], 'utf8');
source = source.replace("  route('library'); render(); poll(); window.setInterval(poll, POLL_MS);\n})();", "  globalThis.__replayTest = { model, applyState, updateRecordingDraft, deleteReplaySession, safeReplayDataUrl };\n})();");
eval(source);
const ui = globalThis.__replayTest;
const replay = (frameId = null, phase = 'ready') => ({ phase, message: phase === 'error' ? 'Replay index is unavailable.' : 'Replay ready.', settings: { enabled: false, retention_days: 7, image_format: 'webp', max_width: 960, quality: 60, interval_seconds: 2, max_bytes: 2 * 1024 * 1024 * 1024 }, sessions: [{ id: 'a'.repeat(32), started_at: 1700000000, frame_count: 2 }], selected_session: 'a'.repeat(32), has_older_frames: true, has_older_sessions: true, frames: [{ frame_id: '1'.repeat(32), session_id: 'a'.repeat(32), recorded_at: 1700000000, width: 960, height: 540, image_format: 'webp', event: 'frame', state: 'redacted_unknown' }, { frame_id: '2'.repeat(32), session_id: 'a'.repeat(32), recorded_at: 1700000001, width: 960, height: 540, image_format: 'webp', event: 'frame', state: 'gameplay' }], stats: { frame_count: 2, session_count: 1, byte_count: 20 }, frame: frameId ? { frame_id: frameId } : null });
const state = (replayState, locked = false) => ({ game_id: 'adopt', games: [], mode: 'dry', session: { phase: locked ? 'running' : 'idle', message: '', can_start: false, acknowledged: false, input_locked: locked, cleanup_failed: false }, preview: {}, binding: {}, readiness: {}, app: {}, template: {}, popup: { phase: 'idle', state: 'unknown', message: '', busy: false, can_check: false, can_resolve: false, allow_reconnect: false }, replay: replayState });
const popupResult = (popupState, canResolve = false) => ({ ...state(replay()), popup: { phase: 'result', state: popupState, message: '', busy: false, can_check: false, can_resolve: canResolve, allow_reconnect: false } });
const recordingControls = [...recording, id('#recording-save')];
ui.model.bridgeReady = true;
ui.applyState(state(replay()));
id('#recording-width').value = '1000'; ui.updateRecordingDraft(); ui.applyState(state(replay()));
if (ui.model.recordingDraft.max_width !== 1000 || id('#recording-width').value !== '1000' || Object.keys(ui.model.recordingDraft).length !== 7) throw new Error('poll overwrote dirty seven-field settings draft');
ui.deleteReplaySession('a'.repeat(32)); ui.applyState(state(replay()));
if (ui.model.pendingDeleteId !== 'a'.repeat(32) || !id('#replay-session-list').children[0].children[2].textContent.includes('Confirm')) throw new Error('delete confirmation was not stable across poll');
ui.applyState(state(replay('1'.repeat(32)))); ui.applyState(state(replay('2'.repeat(32))));
resolvers.shift()({ frame_id: '1'.repeat(32), data_url: 'data:image/webp;base64,QQ==' });
Promise.resolve().then(() => { if (ui.model.replayImageId === '1'.repeat(32)) throw new Error('stale frame replaced current frame'); resolvers.shift()({ frame_id: '2'.repeat(32), data_url: 'data:image/jpeg;base64,Qg==' }); return Promise.resolve(); }).then(() => {
  if (ui.model.replayImageId !== '2'.repeat(32)) throw new Error('current replay frame was not cached');
  ui.applyState(state(replay('1'.repeat(32))));
  if (!id('#replay-frame-state').className.includes('bad') || !id('#replay-frame-state').textContent.includes('redacted unknown')) throw new Error('redacted timeline state was not marked');
  for (const [popupState, kind] of [['protected', 'bad'], ['unknown', 'warn'], ['blocked', 'bad'], ['error', 'bad']]) { ui.applyState(popupResult(popupState)); if (id('#popup-phase').textContent !== popupState || !id('#popup-phase').className.split(' ').includes(kind)) throw new Error(`terminal popup state did not preserve its state: ${popupState}`); }
  ui.applyState(popupResult('bank_reward', true));
  if (id('#popup-phase').textContent !== 'bank reward' || !id('#popup-phase').className.includes('good')) throw new Error('allowed popup state was not positively identified');
  ui.applyState(popupResult('disconnected'));
  if (id('#popup-phase').textContent !== 'disconnected' || !id('#popup-phase').className.split(' ').includes('warn')) throw new Error('reconnect-required popup state was not identified');
  ui.applyState({ ...state(replay()), popup: { phase: 'checking', state: 'verifying', message: '', busy: true, can_check: false, can_resolve: false, allow_reconnect: false } });
  if (id('#popup-phase').textContent !== 'verifying') throw new Error('verifying popup phase was hidden');
  ui.applyState(state(replay(null, 'error'), true));
  if (id('#replay-phase').textContent !== 'Storage error' || !id('#recording-status').textContent.includes('Storage error') || !id('#recording-message').textContent.includes('Save retries') || ui.model.recordingDraft.max_width !== 1000 || !ui.model.recordingDirty || recordingControls.some(node => node.disabled) || !id('#reconnect-checkbox').disabled || id('#replay-frames-older').disabled || id('#replay-sessions-older').disabled) throw new Error(JSON.stringify({ phase: id('#replay-phase').textContent, settings: id('#recording-status').textContent, message: id('#recording-message').textContent, draft: ui.model.recordingDraft, reconnect: id('#reconnect-checkbox').disabled, olderFrames: id('#replay-frames-older').disabled, olderSessions: id('#replay-sessions-older').disabled }));
  for (const phase of ['unavailable', 'closed', 'loading']) { ui.applyState(state(replay(null, phase))); if (!id('#recording-status').textContent.includes(phase === 'loading' ? 'Storage loading' : `Storage ${phase}`) || recordingControls.some(node => !node.disabled)) throw new Error(`recording controls stayed editable for ${phase}`); }
  ui.model.recordingDraft = null; ui.model.recordingDirty = false; ui.applyState(state(replay()));
  if (id('#recording-status').textContent !== 'Off' || recordingControls.some(node => node.disabled)) throw new Error('normal recording-off state was not restored');
  id('#replay-frames-older').fire('click'); id('#replay-sessions-older').fire('click');
  if (!commands.some(item => item.name === 'replay_older' && item.payload.session_id === 'a'.repeat(32)) || !commands.some(item => item.name === 'replay_sessions' && item.payload.older === true)) throw new Error('pagination did not cross command bridge');
  if (!ui.safeReplayDataUrl('data:image/jpeg;base64,QQ==') || ui.safeReplayDataUrl('data:image/png;base64,QQ==')) throw new Error('replay data URL validation failed');
}).catch((error) => { console.error(error); process.exitCode = 1; });
'''
        result = subprocess.run(["node", "-e", script, str(APP)], capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
