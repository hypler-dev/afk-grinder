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
  const CAPTURE_CODES = new Set(['permission', 'window_count', 'window_missing', 'geometry', 'black_frame', 'timeout', 'conversion', 'unavailable', 'unexpected']);
  const CAPTURE_STAGES = new Set(['initialization', 'preflight', 'discovery', 'window_selection', 'filter_geometry', 'display_selection', 'screenshot', 'pixel_conversion', 'frame_validation', 'worker', 'ipc_read', 'worker_exit', 'worker_deadline', 'preview_geometry', 'preview_encoding']);
  const CAPTURE_ERROR_TYPES = new Set(['capture_error', 'attribute_error', 'type_error', 'value_error', 'runtime_error', 'timeout_error', 'unexpected']);
  const model = { state: null, route: 'library', bridgeReady: false, polling: false, previewRequestId: 0, previewGameId: null, image: null, imageId: null, draftArea: null, pendingArea: null, pointer: null, gamesKey: '', candidatesKey: '', roiDrawId: 0, roiObserver: null };

  function bridge() { return window.pywebview && window.pywebview.api; }
  function say(message) { $('#announcer').textContent = message || ''; }
  function showError(message) { const node = $('#error-message'); node.textContent = message || 'Desktop action failed.'; node.hidden = false; window.setTimeout(() => { node.hidden = true; }, 5000); }
  function errorText(error) { return error && typeof error.message === 'string' ? error.message : 'Desktop action failed.'; }
  function captureDiagnostic(error) { if (!error || typeof error !== 'object' || !CAPTURE_CODES.has(error.code) || !CAPTURE_STAGES.has(error.stage) || !CAPTURE_ERROR_TYPES.has(error.error_type)) return 'Preview failed. No input was sent.'; const reason = error.code === 'permission' ? 'Capture permission is missing for this build. On macOS, enable Screen Recording in Privacy & Security, then reopen the app.' : 'Preview failed.'; return `${reason} Diagnostic: ${error.code} at ${error.stage} (${error.error_type}). No input was sent.`; }
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
    const previousPreview = model.state && model.state.preview && model.state.preview.id;
    model.state = state;
    const preview = state.preview || {};
    if (model.pendingArea && preview.area && sameArea(model.pendingArea, preview.area)) { model.draftArea = null; model.pendingArea = null; }
    if (previousGame !== state.game_id || preview.phase === 'empty' || preview.phase === 'error' || preview.id !== previousPreview) {
      if (previousGame !== state.game_id || preview.id !== model.imageId || preview.phase === 'empty' || preview.phase === 'error') clearPreviewImage();
    }
    render();
    const session = state.session || {};
    if (previousSession !== JSON.stringify([session.phase, session.message])) say(session.message);
    if (preview.phase === 'available' || preview.phase === 'historical' || preview.phase === 'checking') fetchPreview(preview.id, state.game_id);
  }

  function clearPreviewImage() { model.image = null; model.imageId = null; model.previewGameId = null; model.draftArea = null; model.pendingArea = null; }
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
    const state = model.state; const inputOk = canUseInput(state); const game = currentGame(state); const session = (state && state.session) || {}; const preview = (state && state.preview) || {}; const binding = (state && state.binding) || {}; const readiness = (state && state.readiness) || {}; const app = (state && state.app) || {}; const template = (state && state.template) || {};
    $$('[data-command]').forEach((button) => { if (button.dataset.command === 'stop') { button.disabled = !model.bridgeReady; return; } button.disabled = !inputOk || !sessionIdle(state); });
    text('#rail-game-name', game ? game.name : 'Game library'); text('#rail-game-status', game ? (game.supported ? 'Input check profile' : 'Preview only') : 'Connecting'); $('#rail-art').src = artFor(game); $('#hero-art').src = artFor(game); text('#hero-title', game ? game.name : 'Waiting for desktop bridge'); text('#hero-copy', game ? (game.supported ? 'A short supervised movement check is the only available input profile.' : 'This profile has concept artwork only. Input, routines, and packs stay unavailable.') : 'The launcher will show only verified native state.'); badge($('#hero-support'), game ? (game.supported ? 'Input check available' : 'Not supported yet') : 'Waiting', game && game.supported ? 'good' : 'warn');
    renderGames(state); text('#session-title', game ? `${game.name} session` : 'Session'); badge($('#session-phase'), phaseLabel(session.phase), session.phase === 'error' || session.phase === 'cleanup_blocked' ? 'bad' : ''); text('#session-heading', session.message || 'Waiting for session state'); text('#session-message', session.cleanup_failed ? 'Cleanup failed. Release held inputs manually and restart the application.' : (session.message || 'No local session data is available yet.')); text('#template-name', template.name || 'Input check'); text('#template-detail', template.steps != null ? `${template.steps} steps · ${template.duration_ms || 0} ms` : 'Native template data will appear here.'); badge($('#start-readiness'), session.can_start ? 'Ready from engine' : 'Not ready', session.can_start ? 'good' : 'warn'); text('#limit-seconds', app.limit_seconds || 30);
    $$('.mode-group button').forEach((button) => { const active = state && state.mode === button.dataset.mode; button.classList.toggle('active', active); button.setAttribute('aria-pressed', String(active)); button.disabled = !inputOk || !sessionIdle(state); }); $('#start-button').disabled = !inputOk || !session.can_start; $('#start-button').textContent = state && state.mode === 'live' ? 'Start live input' : 'Start dry run';
    badge($('#preview-phase'), phaseLabel(preview.phase), preview.phase === 'error' ? 'bad' : ''); const previewImage = $('#preview-image'); const previewEmpty = $('#preview-empty'); if (model.image && model.imageId === preview.id && model.previewGameId === state.game_id) { previewImage.src = model.image; previewImage.hidden = false; previewEmpty.hidden = true; } else { previewImage.removeAttribute('src'); previewImage.hidden = true; previewEmpty.hidden = false; } text('#preview-note', preview.phase === 'error' ? captureDiagnostic(preview.error) : 'A preview does not prove gameplay is ready.');
    text('#binding-message', binding.message || 'Waiting for discovery.'); text('#capture-message', preview.phase === 'error' ? captureDiagnostic(preview.error) : (preview.phase === 'capturing' ? 'Capturing selected window…' : 'Preview stays in memory and is optional.')); text('#readiness-message', Array.isArray(readiness.issues) && readiness.issues.length ? readiness.issues.join(' ') : (readiness.phase === 'ready' ? 'Native checks report ready.' : 'Waiting for native readiness.')); text('#binding-phase', phaseLabel(binding.phase)); text('#readiness-phase', phaseLabel(readiness.phase)); text('#ack-phase', session.acknowledged ? 'Confirmed' : 'Not confirmed'); $('#ack-checkbox').checked = Boolean(session.acknowledged); $('#ack-checkbox').disabled = !inputOk || !sessionIdle(state); $$('.setup-list [data-command]').forEach((button) => { button.disabled = !model.bridgeReady || !sessionIdle(state) || !supported(state); }); $('[data-command="capture"]').disabled = !inputOk || !sessionIdle(state) || binding.phase !== 'bound'; $('[data-command="clear_preview"]').disabled = !inputOk || !sessionIdle(state) || preview.phase === 'empty'; $('[data-command="reset_area"]').disabled = !canEditArea() || !preview.area; renderCandidates(binding, inputOk && sessionIdle(state));
    const cleanup = Boolean(session.cleanup_failed || session.phase === 'cleanup_blocked'); $('#cleanup-banner').hidden = !cleanup; text('#cleanup-message', session.message || 'Release held inputs manually, then restart the application.');
    text('#routine-title', template.name || 'Input check'); text('#routine-copy', game && game.supported ? 'Forward, wait, back. Input only; no game task or reward claim.' : 'This profile cannot run routines.'); const editor = $('#template-json'); if (document.activeElement !== editor) editor.value = template.json || ''; editor.disabled = !inputOk || !sessionIdle(state); $('#template-save').disabled = editor.disabled; badge($('#template-status'), template.valid ? 'Valid' : (template.error || 'Invalid'), template.valid ? 'good' : 'bad');
    const areaEditable = canEditArea(); const canvas = $('#roi-canvas'); canvas.tabIndex = areaEditable ? 0 : -1; canvas.setAttribute('aria-disabled', String(!areaEditable)); text('#settings-limit', app.limit_seconds ? `${app.limit_seconds} seconds` : 'Waiting for backend'); text('#app-version', app.version || 'Waiting for backend'); text('#app-commit', app.commit || 'Waiting for backend'); text('#app-platform', app.platform || 'Waiting for backend'); badge($('#geometry-phase'), phaseLabel(preview.geometry), preview.geometry === 'matched' ? 'good' : ''); $('#area-check').disabled = !areaEditable; $('#roi-panel').classList.toggle('disabled-panel', !areaEditable); drawRoi();
  }

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
  function centeredArea() { const preview = model.state.preview; const maximum = Math.min(preview.width, Math.floor(preview.height * 16 / 9)); const width = Math.max(16, Math.floor(maximum / 16) * 16); const height = width / 16 * 9; return { x: Math.max(0, Math.round((preview.width - width) / 2)), y: Math.max(0, Math.round((preview.height - height) / 2)), width, height }; }
  function clampArea(area) { const preview = model.state.preview; const maximum = Math.min(preview.width, Math.floor(preview.height * 16 / 9)); const width = Math.max(16, Math.min(Math.floor(maximum / 16) * 16, Math.floor(Math.round(area.width) / 16) * 16)); const height = width / 16 * 9; return { x: Math.max(0, Math.min(preview.width - width, Math.round(area.x))), y: Math.max(0, Math.min(preview.height - height, Math.round(area.y))), width, height }; }
  function setDraft(area) { model.draftArea = clampArea(area); drawRoi(); }
  function submitArea() { const preview = model.state && model.state.preview; const area = previewRect(); if (!canEditArea() || !preview || !preview.id || !area) return; model.pendingArea = { ...area }; call('set_area', { preview_id: preview.id, rect: area }); }
  function areaFromPointer(event) {
    const metrics = canvasMetrics(); if (!metrics) return null;
    const bounds = metrics.canvas.getBoundingClientRect(); if (!bounds.width || !bounds.height) return null;
    return { x: Math.round((event.clientX - bounds.left) * metrics.preview.width / bounds.width), y: Math.round((event.clientY - bounds.top) * metrics.preview.height / bounds.height) };
  }

  document.addEventListener('click', (event) => { const routeButton = event.target.closest('[data-route]'); if (routeButton) { route(routeButton.dataset.route); return; } const commandButton = event.target.closest('[data-command]'); if (commandButton && !commandButton.disabled) { if (commandButton.dataset.command === 'reset_area' || commandButton.dataset.command === 'clear_preview') model.draftArea = null; call(commandButton.dataset.command); } });
  $$('.mode-group button').forEach((button) => button.addEventListener('click', () => call('set_mode', { mode: button.dataset.mode })));
  $('#ack-checkbox').addEventListener('change', (event) => call('set_ack', { acknowledged: event.target.checked }));
  $('#template-save').addEventListener('click', () => call('set_template', { json: $('#template-json').value }));
  $('#area-check').addEventListener('click', () => { const preview = model.state && model.state.preview; if (canEditArea() && preview && preview.id) call('check_area', { preview_id: preview.id }); });
  $('#roi-canvas').addEventListener('pointerdown', (event) => { const point = areaFromPointer(event); if (!point || !canEditArea()) return; model.pointer = point; const area = previewRect() || centeredArea(); setDraft({ x: point.x, y: point.y, width: area.width, height: area.height }); event.currentTarget.setPointerCapture(event.pointerId); });
  $('#roi-canvas').addEventListener('pointermove', (event) => { if (!model.pointer || !canEditArea()) { model.pointer = null; return; } const point = areaFromPointer(event); if (!point) return; const area = previewRect() || centeredArea(); setDraft({ ...area, x: point.x - Math.round(area.width / 2), y: point.y - Math.round(area.height / 2) }); });
  $('#roi-canvas').addEventListener('pointerup', (event) => { if (model.pointer && canEditArea()) submitArea(); model.pointer = null; if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); });
  $('#roi-canvas').addEventListener('keydown', (event) => { const preview = model.state && model.state.preview; if (!preview || !canEditArea()) return; let area = previewRect(); if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setDraft(centeredArea()); submitArea(); return; } if (event.key.toLowerCase() === 'r') { event.preventDefault(); model.draftArea = null; call('reset_area'); return; } if (!event.key.startsWith('Arrow')) return; event.preventDefault(); area = area || centeredArea(); const delta = event.shiftKey ? 16 : 1; if (event.key === 'ArrowLeft') area = event.shiftKey ? { ...area, width: area.width - delta, height: Math.round((area.width - delta) * 9 / 16) } : { ...area, x: area.x - delta }; if (event.key === 'ArrowRight') area = event.shiftKey ? { ...area, width: area.width + delta, height: Math.round((area.width + delta) * 9 / 16) } : { ...area, x: area.x + delta }; if (event.key === 'ArrowUp') area = event.shiftKey ? { ...area, height: area.height - 9, width: Math.round((area.height - 9) * 16 / 9) } : { ...area, y: area.y - delta }; if (event.key === 'ArrowDown') area = event.shiftKey ? { ...area, height: area.height + 9, width: Math.round((area.height + 9) * 16 / 9) } : { ...area, y: area.y + delta }; setDraft(area); submitArea(); });
  window.addEventListener('keydown', (event) => { const shortcut = event.metaKey || event.ctrlKey; if (event.key === 'Escape' || (shortcut && event.key === '.')) { event.preventDefault(); call('stop'); } else if (shortcut && event.key === ',') { event.preventDefault(); route('settings'); } });
  window.addEventListener('resize', drawRoi);
  if (window.visualViewport) window.visualViewport.addEventListener('resize', drawRoi);
  if (window.ResizeObserver) { model.roiObserver = new ResizeObserver(() => drawRoi()); model.roiObserver.observe($('#roi-canvas').parentElement); }
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') poll(); });
  route('library'); render(); poll(); window.setInterval(poll, POLL_MS);
})();
