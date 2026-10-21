(() => {
  'use strict';

  const POLL_MS = 250;
  const CATALOG = [
    { id: 'adopt', name: 'Adopt Me', genre: 'Social roleplay', art: 'assets/pet-world.png' },
    { id: 'bee', name: 'Bee Swarm Simulator', genre: 'Collection adventure', art: 'assets/bee-fields.png' },
    { id: 'blox', name: 'Blox Fruits', genre: 'Action adventure', art: 'assets/ocean-adventure.png' },
  ];
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => [...document.querySelectorAll(selector)];
  const CAPTURE_CODES = new Set(['permission', 'window_count', 'window_missing', 'geometry', 'black_frame', 'timeout', 'conversion', 'unavailable', 'stale', 'unexpected']);
  const CAPTURE_STAGES = new Set(['initialization', 'preflight', 'discovery', 'window_selection', 'filter_geometry', 'display_selection', 'screenshot', 'pixel_conversion', 'frame_validation', 'worker', 'ipc_read', 'worker_exit', 'worker_deadline', 'capture_freshness', 'worker_exit_freshness', 'preview_freshness', 'preview_geometry', 'preview_encoding']);
  const CAPTURE_ERROR_TYPES = new Set(['capture_error', 'attribute_error', 'type_error', 'value_error', 'runtime_error', 'timeout_error', 'unexpected']);
  const POPUP_DIAGNOSTIC_STAGES = new Set(["initialization", "model_validation", "worker_start", "warmup", "capture_start", "capture", "content_calibration", "capture_freshness", "recognition_submit", "recognition", "recognition_freshness", "classification", "reporting", "recording", "response_geometry", "response", "verification", "idle", "cleanup"]);
  const POPUP_DIAGNOSTIC_CODES = new Set(["failed", "unavailable", "worker_failed", "worker_timeout", "stale", "layout_changed", "timeout", "closed", "clock_invalid", "interrupted", "phase_changed"]);
  const POPUP_CAPTURE_DIAGNOSTIC_STAGES = new Set(['capture_start', 'capture', 'capture_freshness']);
  const MIB = 1024 * 1024;
  const model = { state: null, route: 'library', bridgeReady: false, polling: false, previewRequestId: 0, previewGameId: null, image: null, imageId: null, draftArea: null, pendingArea: null, pointer: null, areaAttested: false, gamesKey: '', candidatesKey: '', roiDrawId: 0, roiObserver: null, packDrawId: 0, packCanvasKey: '', packAnnouncement: '', packMessageKey: '', packError: '', replayFrameId: null, replayImage: null, replayImageId: null, replayRequestGeneration: 0, replayPlaying: false, replayTimer: null, replayRows: new Map(), pendingDeleteId: null, replayAutoFrameKey: null, recordingDraft: null, recordingDirty: false, recordingPending: null };

  function bridge() { return window.pywebview && window.pywebview.api; }
  function say(message) { $('#announcer').textContent = message || ''; }
  function showError(message) { const node = $('#error-message'); node.textContent = message || 'Desktop action failed.'; node.hidden = false; window.setTimeout(() => { node.hidden = true; }, 5000); }
  function errorText(error) { return error && typeof error.message === 'string' ? error.message : 'Desktop action failed.'; }
  function captureDiagnostic(error) { if (!error || typeof error !== 'object' || !CAPTURE_CODES.has(error.code) || !CAPTURE_STAGES.has(error.stage) || !CAPTURE_ERROR_TYPES.has(error.error_type)) return 'Preview failed. No input was sent.'; const reason = error.code === 'permission' ? 'Capture permission is missing for this build. On macOS, enable Screen Recording in Privacy & Security, then reopen the app.' : error.code === 'stale' ? 'Preview expired before calibration. Capture a new preview and try again.' : 'Preview failed.'; return `${reason} Diagnostic: ${error.code} at ${error.stage} (${error.error_type}). No input was sent.`; }
  function sessionIdle(state) { return state && state.session && ['idle', 'stopped', 'completed', 'error'].includes(state.session.phase); }
  function supported(state) { const game = currentGame(state); return Boolean(game && game.supported); }
  function currentGame(state) { return state && Array.isArray(state.games) ? state.games.find((game) => game.id === state.game_id) : null; }
  function artFor(game) { return game && typeof game.art === 'string' && game.art.startsWith('assets/') ? game.art : 'assets/pet-world.png'; }
  function canUseInput(state) { return Boolean(model.bridgeReady && state && supported(state) && !(state.session && state.session.cleanup_failed)); }
  function canEditArea() { const state = model.state; const preview = state && state.preview; return Boolean(canUseInput(state) && state.session && sessionIdle(state) && !state.session.input_locked && model.image && preview && preview.id); }

  async function call(name, payload = {}) {
    const api = bridge();
    if (!api || typeof api.command !== 'function') { setBridge(false, 'Desktop bridge unavailable.'); return null; }
    try {
      const result = await api.command(name, payload);
      if (!result || result.ok !== true) { showError(errorText(result && result.error)); }
      if (result && result.state) applyState(result.state);
      return result;
    } catch (_) { setBridge(false, 'Desktop bridge unavailable.'); return null; }
  }

  function setBridge(ready, message) {
    model.bridgeReady = ready;
    const node = $('#connection');
    node.textContent = message;
    node.className = `connection ${ready ? 'ok' : 'bad'}`;
    render();
  }

  async function poll() {
    if (document.visibilityState !== 'visible' || model.polling) return;
    const api = bridge();
    if (!api || typeof api.get_state !== 'function') { setBridge(false, 'Desktop bridge unavailable.'); return; }
    model.polling = true;
    try { const state = await api.get_state(); if (state && typeof state === 'object') { model.bridgeReady = true; $('#connection').textContent = 'Desktop bridge connected'; $('#connection').className = 'connection ok'; applyState(state); document.documentElement.dataset.bridgeReady = 'true'; } else { setBridge(false, 'Desktop bridge returned no state.'); } }
    catch (_) { setBridge(false, 'Desktop bridge unavailable.'); }
    finally { model.polling = false; }
  }

  function applyState(state) {
    const previousSession = model.state && JSON.stringify([model.state.session.phase, model.state.session.message]);
    const previousGame = model.state && model.state.game_id;
    const previousPreview = model.state && model.state.preview;
    const previousPreviewKey = previousPreview && JSON.stringify([previousPreview.id, previousPreview.width, previousPreview.height, previousPreview.layout, previousPreview.area]);
    const previousPackKey = packRenderKey(model.state);
    const previousReplayFrameId = model.state && model.state.replay && model.state.replay.frame && model.state.replay.frame.frame_id;
    model.state = state;
    const preview = state.preview || {};
    const replayFrameId = state.replay && state.replay.frame && state.replay.frame.frame_id;
    if (previousReplayFrameId !== replayFrameId) { model.replayFrameId = replayFrameId || null; model.replayImage = null; model.replayImageId = null; model.replayRequestGeneration += 1; }
    if (model.recordingPending && sameReplaySettings(state.replay && state.replay.settings, model.recordingPending)) { model.recordingDraft = null; model.recordingDirty = false; model.recordingPending = null; }
    if (!model.recordingDirty && !model.recordingPending) model.recordingDraft = null;
    const nextPreviewKey = JSON.stringify([preview.id, preview.width, preview.height, preview.layout, preview.area]);
    if (previousPackKey !== packRenderKey(state)) { model.packDrawId += 1; model.packCanvasKey = ''; }
    if (previousGame !== state.game_id || previousPreviewKey !== nextPreviewKey) model.areaAttested = false;
    if (model.pendingArea && preview.area && sameArea(model.pendingArea, preview.area)) { model.draftArea = null; model.pendingArea = null; }
    if (previousGame !== state.game_id || preview.phase === 'empty' || preview.phase === 'error' || preview.id !== (previousPreview && previousPreview.id)) {
      if (previousGame !== state.game_id || preview.id !== model.imageId || preview.phase === 'empty' || preview.phase === 'error') clearPreviewImage();
    }
    render();
    const session = state.session || {};
    if (previousSession !== JSON.stringify([session.phase, session.message])) say(session.message);
    announcePack(state.pack || {});
    if (state.pack && state.pack.phase === 'error') { const error = String(state.pack.message || 'Recognition inspection failed.'); if (error !== model.packError) { model.packError = error; showError(error); } } else model.packError = '';
    if (preview.phase === 'available' || preview.phase === 'historical' || preview.phase === 'checking') fetchPreview(preview.id, state.game_id);
    if (typeof replayFrameId === 'string' && replayFrameId) fetchReplayImage(replayFrameId);
    maybeSelectFirstReplayFrame(state.replay || {});
  }

  function clearPreviewImage() { model.image = null; model.imageId = null; model.previewGameId = null; model.draftArea = null; model.pendingArea = null; model.areaAttested = false; }
  async function fetchPreview(id, gameId) {
    if (!Number.isFinite(id) || id <= 0 || id === model.previewRequestId || model.imageId === id) return;
    const api = bridge(); if (!api || typeof api.get_preview !== 'function') return;
    model.previewRequestId = id;
    try {
      const preview = await api.get_preview(id);
      const current = model.state && model.state.preview;
      if (!preview || preview.id !== id || !current || current.id !== id || model.state.game_id !== gameId || typeof preview.data_url !== 'string') return;
      model.image = preview.data_url; model.imageId = id; model.previewGameId = gameId; render();
    } catch (_) { /* Polling state remains source of truth. */ }
    finally { if (model.previewRequestId === id) model.previewRequestId = 0; }
  }

  function safeReplayDataUrl(value) { return typeof value === 'string' && /^data:image\/(?:webp|jpeg);base64,[A-Za-z0-9+/]+={0,2}$/.test(value); }
  async function fetchReplayImage(frameId) {
    if (model.replayImageId === frameId && model.replayImage) return;
    const api = bridge(); if (!api || typeof api.get_preview !== 'function') return;
    const generation = ++model.replayRequestGeneration;
    try {
      const frame = await api.get_preview({ replay_frame_id: frameId });
      const current = model.state && model.state.replay && model.state.replay.frame;
      if (generation !== model.replayRequestGeneration || !current || current.frame_id !== frameId || !frame || frame.frame_id !== frameId || !safeReplayDataUrl(frame.data_url)) return;
      model.replayImage = frame.data_url; model.replayImageId = frameId; render();
    } catch (_) { /* Replay state remains source of truth. */ }
  }

  function text(selector, value) { const node = $(selector); if (node) node.textContent = value == null ? '' : String(value); }
  function route(name) { model.route = name; $$('.page').forEach((page) => page.classList.toggle('active', page.dataset.page === name)); $$('.nav [data-route]').forEach((button) => { const active = button.dataset.route === name; button.toggleAttribute('aria-current', active); }); text('#crumb', name[0].toUpperCase() + name.slice(1)); }
  function badge(node, value, kind = '') { node.textContent = value || 'Waiting'; node.className = `badge ${kind}`; }
  function phaseLabel(value) { return String(value || 'waiting').replace(/_/g, ' '); }

  function renderGames(state) {
    const grid = $('#game-grid'); const hasState = Boolean(state && Array.isArray(state.games)); const games = hasState ? state.games : CATALOG; const key = JSON.stringify({ hasState, ready: model.bridgeReady, selected: state && state.game_id, games: games.map(({ id, name, genre, supported, art }) => ({ id, name, genre, supported, art })) });
    if (key === model.gamesKey) return;
    model.gamesKey = key; grid.textContent = '';
    for (const game of games) { const card = $('#game-template').content.firstElementChild.cloneNode(true); const image = card.querySelector('img'); image.src = artFor(game); image.alt = `${game.name || 'Game'} original concept art`; const status = card.querySelector('.badge'); badge(status, hasState ? (game.supported ? 'Input check available' : 'Not supported yet') : 'Bridge unavailable', hasState && game.supported ? 'good' : 'warn'); card.querySelector('h3').textContent = game.name || 'Unknown profile'; card.querySelector('p').textContent = game.genre || ''; const open = card.querySelector('button'); open.textContent = hasState && game.supported ? 'Open profile' : 'View details'; open.disabled = !model.bridgeReady || !hasState; open.addEventListener('click', () => call('select_game', { game_id: game.id })); card.classList.toggle('selected', Boolean(state && state.game_id === game.id)); grid.append(card); }
  }

  function render() {
    const state = model.state; const inputOk = canUseInput(state); const game = currentGame(state); const session = (state && state.session) || {}; const preview = (state && state.preview) || {}; const binding = (state && state.binding) || {}; const readiness = (state && state.readiness) || {}; const app = (state && state.app) || {}; const template = (state && state.template) || {}; const popup = (state && state.popup) || {}; const replay = (state && state.replay) || {};
    $$('[data-command]').forEach((button) => { if (button.dataset.command === 'stop') { button.disabled = !model.bridgeReady; return; } button.disabled = !inputOk || !sessionIdle(state); });
    text('#rail-game-name', game ? game.name : 'Game library'); text('#rail-game-status', game ? (game.supported ? 'Input check profile' : 'Preview only') : 'Connecting'); $('#rail-art').src = artFor(game); $('#hero-art').src = artFor(game); text('#hero-title', game ? game.name : 'Waiting for desktop bridge'); text('#hero-copy', game ? (game.supported ? 'A short supervised movement check is the only available input profile.' : 'This profile has concept artwork only. Input, routines, and packs stay unavailable.') : 'The launcher will show only verified native state.'); badge($('#hero-support'), game ? (game.supported ? 'Input check available' : 'Not supported yet') : 'Waiting', game && game.supported ? 'good' : 'warn');
    renderGames(state); text('#session-title', game ? `${game.name} session` : 'Session'); badge($('#session-phase'), phaseLabel(session.phase), session.phase === 'error' || session.phase === 'cleanup_blocked' ? 'bad' : ''); text('#session-heading', session.message || 'Waiting for session state'); text('#session-message', session.cleanup_failed ? 'Cleanup failed. Release held inputs manually and restart the application.' : (session.message || 'No local session data is available yet.')); text('#template-name', template.name || 'Input check'); text('#template-detail', template.steps != null ? `${template.steps} steps · ${template.duration_ms || 0} ms` : 'Native template data will appear here.'); badge($('#start-readiness'), session.can_start ? 'Ready from engine' : 'Not ready', session.can_start ? 'good' : 'warn'); text('#limit-seconds', app.limit_seconds || 30);
    $$('.mode-group button').forEach((button) => { const active = state && state.mode === button.dataset.mode; button.classList.toggle('active', active); button.setAttribute('aria-pressed', String(active)); button.disabled = !inputOk || !sessionIdle(state); }); $('#start-button').disabled = !inputOk || !session.can_start; $('#start-button').textContent = state && state.mode === 'live' ? 'Start live input' : 'Start dry run';
    badge($('#preview-phase'), phaseLabel(preview.phase), preview.phase === 'error' ? 'bad' : ''); const previewImage = $('#preview-image'); const previewEmpty = $('#preview-empty'); if (model.image && model.imageId === preview.id && model.previewGameId === state.game_id) { previewImage.src = model.image; previewImage.hidden = false; previewEmpty.hidden = true; } else { previewImage.removeAttribute('src'); previewImage.hidden = true; previewEmpty.hidden = false; } text('#preview-note', preview.phase === 'error' ? captureDiagnostic(preview.error) : 'A preview does not prove gameplay is ready.');
    text('#binding-message', binding.message || 'Waiting for discovery.'); text('#capture-message', preview.phase === 'error' ? captureDiagnostic(preview.error) : (preview.phase === 'capturing' ? 'Capturing selected window…' : 'Preview stays in memory and is optional.')); text('#readiness-message', Array.isArray(readiness.issues) && readiness.issues.length ? readiness.issues.join(' ') : (readiness.phase === 'ready' ? 'Native checks report ready.' : 'Waiting for native readiness.')); text('#binding-phase', phaseLabel(binding.phase)); text('#readiness-phase', phaseLabel(readiness.phase)); text('#ack-phase', session.acknowledged ? 'Confirmed' : 'Not confirmed'); $('#ack-checkbox').checked = Boolean(session.acknowledged); $('#ack-checkbox').disabled = !inputOk || !sessionIdle(state); $$('.setup-list [data-command]').forEach((button) => { button.disabled = !model.bridgeReady || !sessionIdle(state) || !supported(state); }); $('[data-command="capture"]').disabled = !inputOk || !sessionIdle(state) || binding.phase !== 'bound'; $('[data-command="clear_preview"]').disabled = !inputOk || !sessionIdle(state) || preview.phase === 'empty'; $('[data-command="reset_area"]').disabled = !canEditArea() || !preview.area; renderCandidates(binding, inputOk && sessionIdle(state));
    const cleanup = Boolean(session.cleanup_failed || session.phase === 'cleanup_blocked'); $('#cleanup-banner').hidden = !cleanup; text('#cleanup-message', session.message || 'Release held inputs manually, then restart the application.');
    text('#routine-title', template.name || 'Input check'); text('#routine-copy', game && game.supported ? 'Forward, wait, back. Input only; no game task or reward claim.' : 'This profile cannot run routines.'); const editor = $('#template-json'); if (document.activeElement !== editor) editor.value = template.json || ''; editor.disabled = !inputOk || !sessionIdle(state); $('#template-save').disabled = editor.disabled; badge($('#template-status'), template.valid ? 'Valid' : (template.error || 'Invalid'), template.valid ? 'good' : 'bad');
    const areaEditable = canEditArea(); const canvas = $('#roi-canvas'); canvas.tabIndex = areaEditable ? 0 : -1; canvas.setAttribute('aria-disabled', String(!areaEditable)); renderAreaControls(areaEditable, preview); text('#settings-limit', app.limit_seconds ? `${app.limit_seconds} seconds` : 'Waiting for backend'); text('#app-version', app.version || 'Waiting for backend'); text('#app-commit', app.commit || 'Waiting for backend'); text('#app-platform', app.platform || 'Waiting for backend'); badge($('#geometry-phase'), phaseLabel(preview.geometry), preview.geometry === 'matched' ? 'good' : ''); $('#area-check').disabled = !areaEditable || !model.areaAttested; $('#roi-panel').classList.toggle('disabled-panel', !areaEditable); renderPack((state && state.pack) || {}); renderPopup(popup, session); renderReplay(replay); renderReplaySettings(replay); drawRoi();
  }

  function safePackText(value, fallback = '—') { return typeof value === 'string' && value ? value : fallback; }
  function setPackMessage(value) { const node = $('#pack-message'); if (value === model.packMessageKey) return; model.packMessageKey = value; node.textContent = value; }
  function packRenderKey(state) { const preview = state && state.preview || {}; const pack = state && state.pack || {}; const inspection = pack.inspection || {}; const binding = state && state.binding || {}; return JSON.stringify([state && state.game_id, binding.target_id || binding.id || null, preview.id, preview.width, preview.height, preview.geometry, pack.phase, inspection.status, inspection.state_id, inspection.reason, inspection.preview_id, inspection.width, inspection.height, inspection.anchors]); }
  function normalizePackInspection(state) {
    const pack = state && state.pack; const preview = state && state.preview; const raw = pack && pack.inspection;
    if (!raw || typeof raw !== 'object' || !preview || !Number.isInteger(preview.id) || !Number.isInteger(preview.width) || !Number.isInteger(preview.height) || preview.width <= 0 || preview.height <= 0 || raw.preview_id !== preview.id || raw.width !== preview.width || raw.height !== preview.height) return null;
    const status = ['unknown', 'unstable', 'known', 'blocked'].includes(raw.status) ? raw.status : 'unknown';
    const anchors = Array.isArray(raw.anchors) ? raw.anchors.slice(0, 64).flatMap((anchor) => { if (!anchor || typeof anchor !== 'object' || typeof anchor.id !== 'string' || !anchor.id) return []; const score = typeof anchor.score === 'number' && Number.isFinite(anchor.score) && anchor.score >= 0 && anchor.score <= 1 ? anchor.score : null; const box = anchor.box && typeof anchor.box === 'object' && Number.isInteger(anchor.box.x) && Number.isInteger(anchor.box.y) && Number.isInteger(anchor.box.width) && Number.isInteger(anchor.box.height) && anchor.box.x >= 0 && anchor.box.y >= 0 && anchor.box.width > 0 && anchor.box.height > 0 && anchor.box.x + anchor.box.width <= preview.width && anchor.box.y + anchor.box.height <= preview.height ? { x: anchor.box.x, y: anchor.box.y, width: anchor.box.width, height: anchor.box.height } : null; return [{ id: anchor.id, score, box }]; }) : [];
    return { status, stateId: safePackText(raw.state_id, 'No state'), kind: safePackText(raw.kind, 'Unknown kind'), reason: safePackText(raw.reason, 'No reason supplied'), stableCount: Number.isInteger(raw.stable_count) && raw.stable_count >= 0 && raw.stable_count <= 5 ? raw.stable_count : 0, requiredFrames: Number.isInteger(raw.required_frames) && raw.required_frames >= 0 && raw.required_frames <= 5 ? raw.required_frames : 0, historical: raw.historical === true, previewId: raw.preview_id, width: raw.width, height: raw.height, anchors };
  }
  function announcePack(pack) { const inspection = normalizePackInspection(model.state); const signature = JSON.stringify([pack.phase, pack.message, inspection && inspection.status, inspection && inspection.stateId, inspection && inspection.reason]); if (signature === model.packAnnouncement) return; model.packAnnouncement = signature; say(safePackText(pack.message, inspection ? `${inspection.status} visual inspection.` : 'No local pack selected.')); }
  function renderPack(pack) {
    const inspection = normalizePackInspection(model.state); const busy = Boolean(pack.busy); const canChoose = Boolean(pack.can_choose); const canCheck = Boolean(pack.can_check); const canClear = Boolean(pack.can_clear);
    badge($('#pack-phase'), phaseLabel(pack.phase || 'empty'), pack.phase === 'error' ? 'bad' : (pack.phase === 'ready' || pack.phase === 'result' ? 'good' : '')); text('#pack-id', safePackText(pack.id, 'No local pack selected')); text('#pack-version', safePackText(pack.version)); text('#pack-source', safePackText(pack.source)); setPackMessage(safePackText(pack.message, 'No local pack selected. Recognition inspection cannot activate or start routines.'));
    $('#pack-choose').disabled = !model.bridgeReady || busy || !canChoose; $('#pack-check').disabled = !model.bridgeReady || busy || !canCheck; $('#pack-clear').disabled = !model.bridgeReady || busy || !canClear; $('#pack-check').textContent = busy && pack.phase === 'checking' ? 'Inspecting fresh frames…' : 'Inspect fresh frames';
    const inspectionKind = inspection ? (inspection.status === 'known' ? 'good' : (inspection.status === 'blocked' ? 'bad' : 'warn')) : ''; badge($('#pack-inspection-phase'), inspection ? (inspection.status === 'known' ? 'Visual state seen' : phaseLabel(inspection.status)) : 'No inspection', inspectionKind); text('#pack-inspection-detail', inspection ? `${inspection.stateId} · ${inspection.kind} · ${inspection.reason}${inspection.historical ? ' · Historical' : ''}` : 'No current inspection.'); text('#pack-stability', inspection && inspection.requiredFrames > 0 ? `${inspection.stableCount} of ${inspection.requiredFrames} fresh frames stable.` : '');
    const anchors = $('#pack-anchor-list'); anchors.textContent = ''; if (!inspection || !inspection.anchors.length) { const item = document.createElement('li'); item.textContent = 'No anchor metadata.'; anchors.append(item); } else for (const anchor of inspection.anchors) { const item = document.createElement('li'); const score = anchor.score == null ? 'no score' : anchor.score.toFixed(3); const box = anchor.box ? `${anchor.box.x}, ${anchor.box.y}, ${anchor.box.width}×${anchor.box.height} raw px` : 'no box'; item.textContent = `${anchor.id} · ${score} · ${box}`; anchors.append(item); }
    drawPackInspection(inspection);
  }
  function packCanvasMetrics(inspection) { const canvas = $('#pack-canvas'); if (!inspection || !model.image || model.imageId !== inspection.previewId || model.previewGameId !== model.state.game_id) return null; const maxWidth = Math.min(Math.max(1, canvas.parentElement.clientWidth - 14), inspection.width); const scale = Math.min(maxWidth / inspection.width, 420 / inspection.height); const width = Math.max(1, Math.round(inspection.width * scale)); const height = Math.max(1, Math.round(inspection.height * scale)); return { canvas, width, height, xScale: width / inspection.width, yScale: height / inspection.height, dpr: Math.max(1, window.devicePixelRatio || 1) }; }
  function encodedPreviewDimensions(width, height) { const scale = Math.max(1, Math.ceil(width / 640), Math.ceil(height / 360)); return { width: Math.max(1, Math.floor(width / scale)), height: Math.max(1, Math.floor(height / scale)) }; }
  function drawPackInspection(inspection) {
    const canvas = $('#pack-canvas'); const empty = $('#pack-empty'); const metrics = packCanvasMetrics(inspection); const key = metrics && `${packRenderKey(model.state)}:${model.imageId}:${metrics.width}:${metrics.height}:${metrics.dpr}`;
    if (!metrics) { model.packCanvasKey = ''; canvas.width = 0; canvas.height = 0; canvas.hidden = true; empty.hidden = false; return; }
    if (key === model.packCanvasKey) return; model.packCanvasKey = key; const drawId = ++model.packDrawId; empty.hidden = true; canvas.hidden = false; canvas.style.width = `${metrics.width}px`; canvas.style.height = `${metrics.height}px`; canvas.width = Math.round(metrics.width * metrics.dpr); canvas.height = Math.round(metrics.height * metrics.dpr); const context = canvas.getContext('2d'); const source = model.image; const image = new Image();
    image.onload = () => { const state = model.state; const current = normalizePackInspection(state); const expected = current && encodedPreviewDimensions(current.width, current.height); if (drawId !== model.packDrawId || source !== model.image || !current || !state.preview || current.previewId !== model.imageId || model.previewGameId !== state.game_id || image.naturalWidth !== expected.width || image.naturalHeight !== expected.height) { context.clearRect(0, 0, metrics.width, metrics.height); canvas.hidden = true; empty.hidden = false; return; } context.setTransform(metrics.dpr, 0, 0, metrics.dpr, 0, 0); context.clearRect(0, 0, metrics.width, metrics.height); context.drawImage(image, 0, 0, metrics.width, metrics.height); context.lineWidth = 2; context.strokeStyle = '#50dbf7'; context.fillStyle = '#50dbf722'; for (const anchor of current.anchors) { if (!anchor.box) continue; const { x, y, width, height } = anchor.box; context.fillRect(x * metrics.xScale, y * metrics.yScale, width * metrics.xScale, height * metrics.yScale); context.strokeRect(x * metrics.xScale, y * metrics.yScale, width * metrics.xScale, height * metrics.yScale); } };
    image.src = source;
  }

  function renderAreaControls(editable, preview) {
    const area = previewRect(); const fields = [['#area-x', 'x'], ['#area-y', 'y'], ['#area-width', 'width'], ['#area-height', 'height']];
    for (const [selector, key] of fields) { const node = $(selector); if (document.activeElement !== node) node.value = area ? String(area[key]) : ''; node.disabled = !editable; }
    $('#area-attestation').checked = model.areaAttested; $('#area-attestation').disabled = !editable;
  }

  function popupDiagnostic(popup) {
    const error = popup && popup.diagnostic;
    if (!popup || popup.phase !== 'result' || popup.state !== 'error' || !error || typeof error !== 'object' || Array.isArray(error) || Object.keys(error).sort().join(',') !== 'capture,code,stage' || !POPUP_DIAGNOSTIC_STAGES.has(error.stage) || !POPUP_DIAGNOSTIC_CODES.has(error.code)) return '';
    let detail = `Diagnostic: ${error.stage} / ${error.code}.`;
    if (error.capture !== null) {
      const capture = error.capture;
      if (!POPUP_CAPTURE_DIAGNOSTIC_STAGES.has(error.stage) || !capture || typeof capture !== 'object' || Array.isArray(capture) || Object.keys(capture).sort().join(',') !== 'code,error_type,stage' || !CAPTURE_CODES.has(capture.code) || !CAPTURE_STAGES.has(capture.stage) || !CAPTURE_ERROR_TYPES.has(capture.error_type)) return '';
      detail += ` Capture: ${capture.code} at ${capture.stage} (${capture.error_type}).`;
    }
    return detail;
  }

  function renderPopup(popup, session) {
    const activePhase = ['checking', 'verifying'].includes(popup.state) ? popup.state : popup.phase;
    const resolved = popup.phase === 'result';
    const popupKind = { error: 'bad', protected: 'bad', blocked: 'bad', unknown: 'warn', bank_reward: 'good', disconnected: 'warn', popup_dismissed: 'good', reconnect_requested: 'good' };
    badge($('#popup-phase'), resolved ? phaseLabel(popup.state || 'result') : phaseLabel(activePhase), resolved ? (popupKind[popup.state] || '') : '');
    text('#popup-message', popup.message || 'Checks only approved Adopt Me popups. Unknown, login, purchase, and trade screens remain blocked.');
    const diagnostic = $('#popup-diagnostic'); const detail = popupDiagnostic(popup); if (diagnostic.textContent !== detail) diagnostic.textContent = detail; diagnostic.hidden = !detail;
    $('#popup-check').disabled = !model.bridgeReady || Boolean(popup.busy) || !popup.can_check;
    $('#popup-resolve').disabled = !model.bridgeReady || Boolean(popup.busy) || !popup.can_resolve;
    $('#popup-resolve').textContent = popup.busy ? 'Resolving…' : 'Resolve approved popup';
    $('#reconnect-checkbox').checked = Boolean(popup.allow_reconnect); $('#reconnect-checkbox').disabled = !model.bridgeReady || Boolean(popup.busy) || Boolean(session.input_locked) || session.phase === 'cleanup_blocked' || Boolean(session.cleanup_failed);
  }

  function replaySessions(replay) { return Array.isArray(replay.sessions) ? replay.sessions : []; }
  function replayFrames(replay) { return Array.isArray(replay.frames) ? replay.frames : []; }
  function selectedReplaySessionId(replay) { return typeof replay.selected_session === 'string' ? replay.selected_session : null; }
  function replayPhaseKind(replay) { return ['error', 'unavailable', 'closed', 'failed'].includes(replay.phase) ? 'bad' : (replay.phase === 'ready' && replay.settings && replay.settings.enabled ? 'good' : 'warn'); }
  function replaySettingsAvailable(replay) { return ['ready', 'paused', 'error'].includes(replay.phase); }
  function replayStorageState(replay) {
    if (replay.phase === 'error') return ['Storage error', 'bad'];
    if (replay.phase === 'unavailable') return ['Storage unavailable', 'bad'];
    if (replay.phase === 'closed') return ['Storage closed', 'bad'];
    if (!replaySettingsAvailable(replay)) return ['Storage loading', 'warn'];
    return null;
  }
  function replaySettingsStatus(replay, value, valid) {
    const storage = replayStorageState(replay);
    if (storage) return storage;
    return [value.enabled ? (model.recordingDirty ? 'Unsaved' : 'Enabled locally') : (model.recordingDirty ? 'Unsaved off' : 'Off'), valid ? (value.enabled ? 'good' : 'warn') : 'bad'];
  }
  function replaySessionRow(session, selectedId) {
    let row = model.replayRows.get(session.id); if (!row) { row = document.createElement('div'); row.className = 'replay-session'; const choose = document.createElement('button'); choose.type = 'button'; choose.className = 'secondary'; choose.addEventListener('click', () => { stopReplayPlayback(); model.replayAutoFrameKey = null; call('replay_select', { session_id: choose.dataset.sessionId }); }); const detail = document.createElement('span'); const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'ghost replay-delete'; remove.addEventListener('click', () => deleteReplaySession(remove.dataset.sessionId)); row.append(choose, detail, remove); model.replayRows.set(session.id, row); }
    const [choose, detail, remove] = row.children; choose.dataset.sessionId = session.id; choose.textContent = formatReplayTime(session.started_at); choose.disabled = !model.bridgeReady; choose.setAttribute('aria-pressed', String(session.id === selectedId)); detail.textContent = `${session.frame_count || 0} frames`; remove.dataset.sessionId = session.id; const confirming = model.pendingDeleteId === session.id; remove.textContent = confirming ? 'Confirm delete' : 'Delete'; remove.disabled = !model.bridgeReady; if (confirming) { let cancel = row.querySelector('.replay-cancel'); if (!cancel) { cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'ghost replay-cancel'; cancel.textContent = 'Cancel'; cancel.addEventListener('click', () => { model.pendingDeleteId = null; render(); }); row.append(cancel); } } else { const cancel = row.querySelector('.replay-cancel'); if (cancel) cancel.remove(); } return row;
  }
  function renderReplay(replay) {
    const sessions = replaySessions(replay); const frames = replayFrames(replay); const frame = replay.frame || null; const selectedSessionId = selectedReplaySessionId(replay); const list = $('#replay-session-list'); const seen = new Set(); for (const session of sessions) { seen.add(session.id); list.append(replaySessionRow(session, selectedSessionId)); } for (const [id, row] of model.replayRows) if (!seen.has(id)) { row.remove(); model.replayRows.delete(id); if (model.pendingDeleteId === id) model.pendingDeleteId = null; }
    const stats = replay.stats || {}; text('#replay-stats', `${stats.session_count || sessions.length || 0} sessions · ${stats.frame_count || 0} frames · ${formatBytes(stats.byte_count || 0)}`); $('#replay-empty').hidden = sessions.length > 0; const storage = replayStorageState(replay); badge($('#replay-phase'), storage ? storage[0] : (replay.settings && replay.settings.enabled ? phaseLabel(replay.phase || 'ready') : 'Recording off'), storage ? storage[1] : replayPhaseKind(replay)); text('#replay-message', replay.message || 'Replay history is unavailable.');
    const image = $('#replay-image'); const empty = $('#replay-image-empty'); const dataUrl = frame && frame.frame_id === model.replayImageId ? model.replayImage : null; const frameInfo = frame && frames.find((item) => item.frame_id === frame.frame_id); if (dataUrl) { image.src = dataUrl; image.hidden = false; empty.hidden = true; } else { image.removeAttribute('src'); image.hidden = true; empty.hidden = false; }
    const frameState = frameInfo && String(frameInfo.state || 'recorded'); const redacted = frameState && frameState.startsWith('redacted_'); text('#replay-frame-detail', frameInfo ? `${formatReplayTime(frameInfo.recorded_at)} · ${frameInfo.width || '?'}×${frameInfo.height || '?'} · ${frameInfo.image_format || 'image'} · ${frameInfo.event || 'frame'} ${frameState}` : 'Select a private session to inspect known-content frames.'); badge($('#replay-frame-state'), frameInfo ? phaseLabel(frameState) : 'No frame', frameInfo ? (redacted ? 'bad' : 'good') : '');
    const currentIndex = Math.max(0, frames.findIndex((item) => item.frame_id === (frame && frame.frame_id))); const scrubber = $('#replay-scrubber'); scrubber.max = String(Math.max(0, frames.length - 1)); scrubber.value = String(currentIndex); scrubber.disabled = !model.bridgeReady || !frames.length; $('#replay-prev').disabled = scrubber.disabled || currentIndex <= 0; $('#replay-next').disabled = scrubber.disabled || currentIndex >= frames.length - 1; $('#replay-play').disabled = scrubber.disabled; $('#replay-play').textContent = model.replayPlaying ? 'Pause' : 'Play'; $('#replay-play').setAttribute('aria-pressed', String(model.replayPlaying)); $('#replay-frames-newest').disabled = !model.bridgeReady || !selectedSessionId; $('#replay-frames-older').disabled = !model.bridgeReady || !selectedSessionId || !replay.has_older_frames; $('#replay-sessions-newest').disabled = !model.bridgeReady; $('#replay-sessions-older').disabled = !model.bridgeReady || !replay.has_older_sessions;
  }

  function defaultReplaySettings() { return { enabled: false, retention_days: 7, image_format: 'webp', max_width: 960, quality: 60, interval_seconds: 2, max_bytes: 2 * 1024 * MIB }; }
  function replaySettingsDraft(settings) { const value = settings || defaultReplaySettings(); return { enabled: Boolean(value.enabled), retention_days: Number(value.retention_days), image_format: value.image_format, max_width: Number(value.max_width), quality: Number(value.quality), interval_seconds: Number(value.interval_seconds), max_bytes: Number(value.max_bytes) }; }
  function sameReplaySettings(first, second) { return Boolean(first && second) && ['enabled', 'retention_days', 'image_format', 'max_width', 'quality', 'interval_seconds', 'max_bytes'].every((key) => first[key] === second[key]); }
  function validReplaySettings(value) { return Boolean(value) && typeof value.enabled === 'boolean' && Number.isInteger(value.retention_days) && value.retention_days >= 1 && value.retention_days <= 365 && ['webp', 'jpeg'].includes(value.image_format) && Number.isInteger(value.max_width) && value.max_width >= 320 && value.max_width <= 1920 && Number.isInteger(value.quality) && value.quality >= 30 && value.quality <= 85 && Number.isInteger(value.interval_seconds) && value.interval_seconds >= 1 && value.interval_seconds <= 30 && Number.isInteger(value.max_bytes) && value.max_bytes >= 100 * MIB && value.max_bytes <= 20480 * MIB; }
  function renderReplaySettings(replay) {
    const settings = replay.settings;
    if (!model.recordingDraft) model.recordingDraft = replaySettingsDraft(settings); const value = model.recordingDraft; const fields = [['#recording-enabled', 'enabled'], ['#recording-days', 'retention_days'], ['#recording-format', 'image_format'], ['#recording-width', 'max_width'], ['#recording-quality', 'quality'], ['#recording-interval', 'interval_seconds']];
    const available = replaySettingsAvailable(replay);
    for (const [selector, key] of fields) { const node = $(selector); if (document.activeElement !== node) node[key === 'enabled' ? 'checked' : 'value'] = key === 'enabled' ? Boolean(value[key]) : String(value[key]); node.disabled = !model.bridgeReady || !available; }
    const cap = $('#recording-cap'); if (document.activeElement !== cap) cap.value = String(Math.round(value.max_bytes / MIB)); cap.disabled = !model.bridgeReady || !available; const valid = validReplaySettings(value); $('#recording-save').disabled = !model.bridgeReady || !available || !valid || Boolean(model.recordingPending); const [status, kind] = replaySettingsStatus(replay, value, valid); badge($('#recording-status'), status, kind); text('#recording-message', replay.phase === 'error' ? `${replay.message || 'Replay storage error.'} Save retries these settings when storage recovers.` : (replay.message || 'Replay settings are local only.'));
  }
  function formatReplayTime(seconds) { const value = Number(seconds); return Number.isFinite(value) && value > 0 ? new Date(value * 1000).toLocaleString() : 'Unknown time'; }
  function updateRecordingDraft() { const value = { enabled: $('#recording-enabled').checked, retention_days: Number($('#recording-days').value), image_format: $('#recording-format').value, max_width: Number($('#recording-width').value), quality: Number($('#recording-quality').value), interval_seconds: Number($('#recording-interval').value), max_bytes: Number($('#recording-cap').value) * MIB }; model.recordingDraft = value; model.recordingDirty = true; model.recordingPending = null; render(); }

  function formatBytes(value) { if (!Number.isFinite(value) || value <= 0) return '0 MiB'; return `${(value / MIB).toFixed(value >= MIB ? 1 : 2)} MiB`; }
  function deleteReplaySession(sessionId) { if (model.pendingDeleteId === sessionId) { model.pendingDeleteId = null; call('replay_delete', { session_id: sessionId }); return; } model.pendingDeleteId = sessionId; say('Press Confirm delete again, or Cancel, to remove this local replay session.'); render(); }
  function maybeSelectFirstReplayFrame(replay) { const sessionId = selectedReplaySessionId(replay); const frames = replayFrames(replay); if (!sessionId || replay.frame || !frames.length) return; const key = `${sessionId}:${frames[0].frame_id}`; if (model.replayAutoFrameKey === key) return; model.replayAutoFrameKey = key; call('replay_frame', { frame_id: frames[0].frame_id }); }
  function stopReplayPlayback() { model.replayPlaying = false; if (model.replayTimer) { window.clearInterval(model.replayTimer); model.replayTimer = null; } }
  function moveReplayFrame(delta) { const replay = (model.state && model.state.replay) || {}; const frames = replayFrames(replay); const currentId = replay.frame && replay.frame.frame_id; const index = frames.findIndex((item) => item.frame_id === currentId); const next = frames[index + delta]; if (next) call('replay_frame', { frame_id: next.frame_id }); else stopReplayPlayback(); }
  function toggleReplayPlayback() { if (model.replayPlaying) { stopReplayPlayback(); render(); return; } model.replayPlaying = true; model.replayTimer = window.setInterval(() => moveReplayFrame(1), 900); render(); }

  function renderCandidates(binding, enabled) { const row = $('#candidate-row'); const holder = $('#candidate-buttons'); const candidates = Array.isArray(binding.candidates) ? binding.candidates : []; const key = JSON.stringify({ phase: binding.phase, enabled, candidates }); if (key === model.candidatesKey) return; model.candidatesKey = key; holder.textContent = ''; row.hidden = binding.phase !== 'multiple' || !candidates.length; for (const candidate of candidates) { const button = document.createElement('button'); button.type = 'button'; button.className = 'secondary'; button.textContent = candidate.label || 'Verified Roblox window'; button.disabled = !enabled; button.addEventListener('click', () => call('select_target', { target_id: candidate.id })); holder.append(button); } }

  function sameArea(first, second) { return first && second && first.x === second.x && first.y === second.y && first.width === second.width && first.height === second.height; }
  function previewRect() { const preview = model.state && model.state.preview; return model.draftArea || (preview && preview.area); }
  function canvasMetrics() {
    const canvas = $('#roi-canvas'); const preview = model.state && model.state.preview;
    if (!model.image || !preview || !preview.width || !preview.height) return null;
    const maxWidth = Math.min(Math.max(1, canvas.parentElement.clientWidth - 14), preview.width);
    const scale = Math.min(maxWidth / preview.width, 420 / preview.height);
    const width = Math.max(1, Math.round(preview.width * scale)); const height = Math.max(1, Math.round(preview.height * scale));
    return { canvas, preview, width, height, xScale: width / preview.width, yScale: height / preview.height, dpr: Math.max(1, window.devicePixelRatio || 1) };
  }
  function drawRoi() {
    const metrics = canvasMetrics(); const canvas = $('#roi-canvas'); const empty = $('#roi-empty'); const drawId = ++model.roiDrawId;
    if (!metrics) { canvas.width = 0; canvas.height = 0; canvas.hidden = true; empty.hidden = false; return; }
    empty.hidden = true; canvas.hidden = false;
    canvas.style.width = `${metrics.width}px`; canvas.style.height = `${metrics.height}px`;
    canvas.width = Math.round(metrics.width * metrics.dpr); canvas.height = Math.round(metrics.height * metrics.dpr);
    const context = canvas.getContext('2d'); context.setTransform(metrics.dpr, 0, 0, metrics.dpr, 0, 0);
    const image = new Image(); const source = model.image;
    image.onload = () => {
      if (drawId !== model.roiDrawId || source !== model.image) return;
      context.clearRect(0, 0, metrics.width, metrics.height); context.drawImage(image, 0, 0, metrics.width, metrics.height);
      const area = previewRect(); if (!area) return;
      const x = area.x * metrics.xScale; const y = area.y * metrics.yScale; const width = area.width * metrics.xScale; const height = area.height * metrics.yScale;
      context.lineWidth = 2; context.strokeStyle = '#50dbf7'; context.fillStyle = '#50dbf722'; context.fillRect(x, y, width, height); context.strokeRect(x, y, width, height);
    };
    image.src = source;
  }
  function centeredArea() { const preview = model.state.preview; const width = Math.max(1, Math.round(preview.width * .8)); const height = Math.max(1, Math.round(preview.height * .8)); return { x: Math.max(0, Math.round((preview.width - width) / 2)), y: Math.max(0, Math.round((preview.height - height) / 2)), width, height }; }
  function clampArea(area) { const preview = model.state.preview; const width = Math.max(1, Math.min(preview.width, Math.round(area.width))); const height = Math.max(1, Math.min(preview.height, Math.round(area.height))); return { x: Math.max(0, Math.min(preview.width - width, Math.round(area.x))), y: Math.max(0, Math.min(preview.height - height, Math.round(area.y))), width, height }; }
  function setDraft(area) { model.draftArea = clampArea(area); model.areaAttested = false; drawRoi(); renderAreaControls(canEditArea(), model.state.preview); }
  function submitArea() { const preview = model.state && model.state.preview; const area = previewRect(); if (!canEditArea() || !preview || !preview.id || !area) return; model.pendingArea = { ...area }; call('set_area', { preview_id: preview.id, rect: area }); }
  function areaFromPointer(event) {
    const metrics = canvasMetrics(); if (!metrics) return null;
    const bounds = metrics.canvas.getBoundingClientRect(); if (!bounds.width || !bounds.height) return null;
    return { x: Math.round((event.clientX - bounds.left) * metrics.preview.width / bounds.width), y: Math.round((event.clientY - bounds.top) * metrics.preview.height / bounds.height) };
  }

  document.addEventListener('click', (event) => { const routeButton = event.target.closest('[data-route]'); if (routeButton) { if (routeButton.dataset.route !== 'replay') stopReplayPlayback(); route(routeButton.dataset.route); return; } const commandButton = event.target.closest('[data-command]'); if (commandButton && !commandButton.disabled) { if (commandButton.dataset.command === 'reset_area' || commandButton.dataset.command === 'clear_preview') { model.draftArea = null; model.areaAttested = false; } call(commandButton.dataset.command); } });
  $$('.mode-group button').forEach((button) => button.addEventListener('click', () => call('set_mode', { mode: button.dataset.mode })));
  $('#ack-checkbox').addEventListener('change', (event) => call('set_ack', { acknowledged: event.target.checked }));
  $('#template-save').addEventListener('click', () => call('set_template', { json: $('#template-json').value }));
  $('#area-attestation').addEventListener('change', (event) => { model.areaAttested = Boolean(event.target.checked); render(); });
  $$('.area-fields input').forEach((field) => field.addEventListener('change', () => { const area = previewRect() || centeredArea(); const value = Number(field.value); if (Number.isInteger(value)) setDraft({ ...area, [field.id.replace('area-', '')]: value }); }));
  $('#area-check').addEventListener('click', () => { const preview = model.state && model.state.preview; if (canEditArea() && model.areaAttested && preview && preview.id) call('check_area', { preview_id: preview.id, attested: true }); });
  $('#roi-canvas').addEventListener('pointerdown', (event) => { const point = areaFromPointer(event); if (!point || !canEditArea()) return; model.pointer = point; setDraft({ x: point.x, y: point.y, width: 1, height: 1 }); event.currentTarget.setPointerCapture(event.pointerId); });
  $('#roi-canvas').addEventListener('pointermove', (event) => { if (!model.pointer || !canEditArea()) { model.pointer = null; return; } const point = areaFromPointer(event); if (!point) return; const x = Math.min(model.pointer.x, point.x); const y = Math.min(model.pointer.y, point.y); setDraft({ x, y, width: Math.abs(point.x - model.pointer.x) + 1, height: Math.abs(point.y - model.pointer.y) + 1 }); });
  $('#roi-canvas').addEventListener('pointerup', (event) => { if (model.pointer && canEditArea()) submitArea(); model.pointer = null; if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); });
  $('#roi-canvas').addEventListener('keydown', (event) => { const preview = model.state && model.state.preview; if (!preview || !canEditArea()) return; let area = previewRect(); if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setDraft(centeredArea()); submitArea(); return; } if (event.key.toLowerCase() === 'r') { event.preventDefault(); model.draftArea = null; model.areaAttested = false; call('reset_area'); return; } if (!event.key.startsWith('Arrow')) return; event.preventDefault(); area = area || centeredArea(); if (event.shiftKey) { if (event.key === 'ArrowLeft') area = { ...area, width: area.width - 1 }; if (event.key === 'ArrowRight') area = { ...area, width: area.width + 1 }; if (event.key === 'ArrowUp') area = { ...area, height: area.height - 1 }; if (event.key === 'ArrowDown') area = { ...area, height: area.height + 1 }; } else { if (event.key === 'ArrowLeft') area = { ...area, x: area.x - 1 }; if (event.key === 'ArrowRight') area = { ...area, x: area.x + 1 }; if (event.key === 'ArrowUp') area = { ...area, y: area.y - 1 }; if (event.key === 'ArrowDown') area = { ...area, y: area.y + 1 }; } setDraft(area); submitArea(); });
  $('#popup-check').addEventListener('click', () => call('popup_check', {}));
  $('#popup-resolve').addEventListener('click', () => call('popup_resolve', {}));
  $('#pack-choose').addEventListener('click', () => call('pack_choose', {}));
  $('#pack-check').addEventListener('click', () => call('pack_check', {}));
  $('#pack-clear').addEventListener('click', () => call('pack_clear', {}));
  $('#reconnect-checkbox').addEventListener('change', (event) => call('set_reconnect', { enabled: Boolean(event.target.checked) }));
  $('#replay-prev').addEventListener('click', () => moveReplayFrame(-1));
  $('#replay-next').addEventListener('click', () => moveReplayFrame(1));
  $('#replay-play').addEventListener('click', toggleReplayPlayback);
  $('#replay-scrubber').addEventListener('input', (event) => { const replay = (model.state && model.state.replay) || {}; const next = replayFrames(replay)[Number(event.target.value)]; if (next) { stopReplayPlayback(); call('replay_frame', { frame_id: next.frame_id }); } });
  $('#replay-frames-newest').addEventListener('click', () => { const replay = (model.state && model.state.replay) || {}; const sessionId = selectedReplaySessionId(replay); if (sessionId) { model.replayAutoFrameKey = null; call('replay_select', { session_id: sessionId }); } });
  $('#replay-frames-older').addEventListener('click', () => { const replay = (model.state && model.state.replay) || {}; const sessionId = selectedReplaySessionId(replay); if (sessionId) { model.replayAutoFrameKey = null; call('replay_older', { session_id: sessionId }); } });
  $('#replay-sessions-newest').addEventListener('click', () => call('replay_sessions', { older: false }));
  $('#replay-sessions-older').addEventListener('click', () => call('replay_sessions', { older: true }));
  $$('#recording-enabled,#recording-days,#recording-format,#recording-width,#recording-quality,#recording-interval,#recording-cap').forEach((node) => node.addEventListener('input', updateRecordingDraft));
  $('#recording-save').addEventListener('click', () => { const settings = model.recordingDraft; if (!validReplaySettings(settings)) { render(); return; } model.recordingPending = { ...settings }; call('replay_settings', { settings }); render(); });
  window.addEventListener('keydown', (event) => { const shortcut = event.metaKey || event.ctrlKey; if (event.key === 'Escape' || (shortcut && event.key === '.')) { event.preventDefault(); call('stop'); } else if (shortcut && event.key === ',') { event.preventDefault(); route('settings'); } });
  function redrawPreviews() { drawRoi(); drawPackInspection(normalizePackInspection(model.state)); }
  window.addEventListener('resize', redrawPreviews);
  if (window.visualViewport) window.visualViewport.addEventListener('resize', redrawPreviews);
  if (window.ResizeObserver) { model.roiObserver = new ResizeObserver(redrawPreviews); model.roiObserver.observe($('#roi-canvas').parentElement); model.roiObserver.observe($('#pack-canvas').parentElement); }
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') poll(); });
  route('library'); render(); poll(); window.setInterval(poll, POLL_MS);
})();
