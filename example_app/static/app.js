// Bearer tokens stay in memory. The server's HttpOnly refresh cookie restores login.
const state = { token: null, user: null, selected: null, notes: [], total: 0, offset: 0, limit: 5, mode: 'login' };
const $ = id => document.getElementById(id);
let listSequence = 0;
let selectionSequence = 0;
let searchTimer;
let sessionGeneration = 0;
let refreshPromise = null;

function notice(message, error = false) {
  $('notice').textContent = message;
  $('notice').classList.toggle('error', error);
  $('notice').hidden = !message;
}

// This one client helper handles JSON, bearer auth, errors, and empty 204 responses.
async function api(path, { method = 'GET', data, authenticated = true, retry = true } = {}) {
  const token = state.token;
  const generation = sessionGeneration;
  // Cookie-using endpoints require this header; cross-origin HTML forms cannot set it.
  const headers = { 'X-Notebook-Request': '1' };
  if (data !== undefined) headers['Content-Type'] = 'application/json';
  if (authenticated && token) headers.Authorization = `Bearer ${token}`;
  let response;
  try {
    response = await fetch(path, { method, headers, credentials: 'same-origin', cache: 'no-store',
      body: data === undefined ? undefined : JSON.stringify(data) });
  } catch {
    throw new Error('Could not reach the notebook. Check that the server is running and try again.');
  }
  const result = response.status === 204 ? null : await response.json();
  // Ignore a response from a previous login rather than exposing it in another account.
  if (authenticated && generation !== sessionGeneration) throw new DOMException('Login changed', 'AbortError');
  // Share one refresh across concurrent requests, then retry the original request once.
  if (response.status === 401 && authenticated && retry) {
    try { await renewLogin(); }
    catch (error) {
      if (error.status === 401) {
        leaveNotebook();
        throw new Error('Your login has ended. Log in again to continue.');
      }
      throw error;
    }
    return api(path, { method, data, authenticated, retry: false });
  }
  if (response.status === 401 && authenticated) {
    leaveNotebook();
    throw new Error('Your login has ended. Log in again to continue.');
  }
  if (!response.ok) {
    const wait = Number(response.headers.get('Retry-After')) || result.retry_after || 0;
    const error = new Error((result.error || `Request failed (${response.status}).`) + (wait ? `. Try again in ${wait} seconds.` : ''));
    error.status = response.status;
    error.retryAfter = wait;
    throw error;
  }
  return { data: result, headers: response.headers };
}

function renewLogin() {
  if (!refreshPromise) {
    const generation = sessionGeneration;
    const previousUser = state.user?.id;
    refreshPromise = api('/api/refresh', { method: 'POST', authenticated: false })
      .then(({ data }) => {
        if (generation !== sessionGeneration) throw new DOMException('Login changed', 'AbortError');
        // Another tab may have logged into a different account using the shared cookie.
        // Never retry an old account's pending write using that new account's identity.
        if (previousUser && previousUser !== data.user.id) {
          leaveNotebook();
          throw new Error('This browser changed accounts. Reload to open the current notebook.');
        }
        state.token = data.access_token;
        return data;
      }).finally(() => { refreshPromise = null; });
  }
  return refreshPromise;
}

async function enterNotebook(login, message) {
  sessionGeneration++;
  state.token = login.access_token;
  const { data: user } = await api('/api/me');
  state.user = user;
  $('auth-password').value = '';
  $('username').textContent = user.id;
  $('welcome').hidden = true;
  $('workspace').hidden = false;
  $('account').hidden = false;
  showNote(null);
  await loadNotes();
  notice(message);
}

async function restoreNotebook() {
  const buttons = [$('auth-submit'), $('login-mode'), $('signup-mode')];
  buttons.forEach(button => { button.disabled = true; });
  notice('Checking your login…');
  try { await enterNotebook(await renewLogin(), 'Welcome back.'); }
  catch (error) {
    leaveNotebook();
    // A new visitor simply has no refresh cookie; other failures deserve a visible message.
    notice(error.status === 401 ? '' : error.message, error.status !== 401);
  }
  finally { buttons.forEach(button => { button.disabled = false; }); }
}

async function action(callback, button) {
  if (button) { button.disabled = true; button.setAttribute('aria-busy', 'true'); }
  try { await callback(); }
  catch (error) { if (error.name !== 'AbortError') notice(error.message, true); }
  finally { if (button) { button.disabled = false; button.removeAttribute('aria-busy'); } }
}

function authMode(mode) {
  state.mode = mode;
  const signup = mode === 'signup';
  $('signup-mode').setAttribute('aria-pressed', String(signup));
  $('login-mode').setAttribute('aria-pressed', String(!signup));
  $('auth-title').textContent = signup ? 'Start your notebook' : 'Open your notebook';
  $('auth-description').textContent = signup ? 'Choose a username and a long password. Your notes belong to you.' : 'Log in to pick up where you left off.';
  $('auth-submit').textContent = signup ? 'Create account' : 'Log in';
  $('auth-password').autocomplete = signup ? 'new-password' : 'current-password';
  notice('');
}

function leaveNotebook() {
  sessionGeneration++;
  state.token = null;
  state.user = null;
  state.notes = [];
  state.total = 0;
  state.offset = 0;
  listSequence++;
  selectionSequence++;
  $('note-list').replaceChildren();
  $('search').value = '';
  $('pinned-filter').checked = false;
  showNote(null);
  $('workspace').hidden = true;
  $('account').hidden = true;
  $('welcome').hidden = false;
  $('username').textContent = '';
  $('auth-password').value = '';
}

function dirty() {
  const original = state.selected || { title: '', body: '', pinned: false };
  return $('note-title').value !== original.title || $('note-body').value !== original.body || $('note-pinned').checked !== original.pinned;
}

function mayDiscard() {
  return !dirty() || window.confirm('Discard your unsaved changes?');
}

function updateDraftState() {
  $('character-count').textContent = `${$('note-body').value.length.toLocaleString()} / 10,000`;
  $('save-state').textContent = dirty() ? 'Unsaved changes' : state.selected ? 'Saved' : 'Ready when you are';
}

function showNote(note) {
  state.selected = note ? structuredClone(note) : null;
  $('note-title').value = note?.title || '';
  $('note-body').value = note?.body || '';
  $('note-pinned').checked = note?.pinned || false;
  $('editor-heading').textContent = note ? 'Edit note' : 'New note';
  $('save-note').textContent = note ? 'Save changes' : 'Save note';
  $('discard').textContent = note ? 'Discard changes' : 'Clear draft';
  $('delete-note').hidden = !note;
  $('note-date').textContent = note ? `Last saved ${new Date(note.updated_at).toLocaleString()}` : '';
  updateDraftState();
}

function renderNotes() {
  $('note-list').replaceChildren();
  for (const note of state.notes) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'note-item';
    button.setAttribute('aria-current', String(note.id === state.selected?.id));
    const title = document.createElement('strong');
    title.textContent = note.title;
    const excerpt = document.createElement('span');
    excerpt.className = 'excerpt';
    excerpt.textContent = note.body.replace(/\s+/g, ' ').slice(0, 85) || 'Empty note';
    const meta = document.createElement('span');
    meta.className = 'note-meta';
    meta.textContent = `${note.pinned ? 'Pinned · ' : ''}${new Date(note.updated_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}`;
    button.append(title, excerpt, meta);
    button.addEventListener('click', () => action(() => selectNote(note.id)));
    $('note-list').append(button);
  }
  $('empty-list').hidden = state.total !== 0;
  $('empty-list').textContent = $('search').value || $('pinned-filter').checked
    ? 'No notes match this filter. Try another search or turn off Pinned only.'
    : 'Your first note starts in the editor. Give it a title and save it.';
  $('list-summary').textContent = state.total ? `${state.offset + 1}–${Math.min(state.offset + state.limit, state.total)} of ${state.total} notes` : 'No notes yet';
  $('pagination').hidden = state.total <= state.limit;
  $('previous').disabled = state.offset === 0;
  $('next').disabled = state.offset + state.limit >= state.total;
  $('page-number').textContent = `Page ${Math.floor(state.offset / state.limit) + 1}`;
}

async function loadNotes() {
  const sequence = ++listSequence;
  const query = new URLSearchParams({ limit: state.limit, offset: state.offset });
  const search = $('search').value.trim();
  if (search) query.set('q', search);
  if ($('pinned-filter').checked) query.set('pinned', 'true');
  const { data } = await api(`/api/notes?${query}`);
  if (sequence !== listSequence) return;
  // If deletion emptied the last page, show the last remaining page instead.
  if (data.total && state.offset >= data.total) {
    state.offset = Math.floor((data.total - 1) / state.limit) * state.limit;
    return loadNotes();
  }
  if (!data.total) state.offset = 0;
  state.notes = data.items;
  state.total = data.total;
  renderNotes();
}

async function selectNote(id) {
  if (id === state.selected?.id || !mayDiscard()) return;
  const sequence = ++selectionSequence;
  const { data } = await api(`/api/notes/${encodeURIComponent(id)}`);
  if (sequence !== selectionSequence) return;
  showNote(data);
  renderNotes();
  notice('');
  if (window.matchMedia('(max-width: 760px)').matches) $('editor-heading').scrollIntoView({ block: 'start' });
}

$('login-mode').addEventListener('click', () => authMode('login'));
$('signup-mode').addEventListener('click', () => authMode('signup'));
$('auth-form').addEventListener('submit', event => {
  event.preventDefault();
  const credentials = { username: $('auth-username').value, password: $('auth-password').value };
  const signup = state.mode === 'signup';
  action(async () => {
    if (signup) await api('/api/signup', { method: 'POST', data: credentials, authenticated: false });
    const { data: login } = await api('/api/login', { method: 'POST', data: credentials, authenticated: false });
    await enterNotebook(login, signup ? 'Your notebook is ready. Write your first note.' : 'Welcome back.');
    $('note-title').focus();
  }, $('auth-submit'));
});

$('note-form').addEventListener('input', updateDraftState);
$('note-form').addEventListener('submit', event => {
  event.preventDefault();
  const id = state.selected?.id;
  const values = { title: $('note-title').value, body: $('note-body').value, pinned: $('note-pinned').checked };
  action(async () => {
    const { data } = await api(id ? `/api/notes/${encodeURIComponent(id)}` : '/api/notes', { method: id ? 'PATCH' : 'POST', data: values });
    selectionSequence++;
    showNote(data);
    state.offset = 0;
    await loadNotes();
    notice('Note saved.');
  }, $('save-note'));
});

$('new-note').addEventListener('click', () => {
  if (!mayDiscard()) return;
  selectionSequence++;
  showNote(null);
  renderNotes();
  notice('');
  $('note-title').focus();
});
$('discard').addEventListener('click', () => {
  if (!mayDiscard()) return;
  showNote(state.selected);
  notice('');
});
$('delete-note').addEventListener('click', () => {
  const id = state.selected?.id;
  if (!id || !window.confirm('Delete this note? This cannot be undone.')) return;
  action(async () => {
    await api(`/api/notes/${encodeURIComponent(id)}`, { method: 'DELETE' });
    selectionSequence++;
    showNote(null);
    await loadNotes();
    notice('Note deleted.');
  }, $('delete-note'));
});
$('search').addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { state.offset = 0; action(loadNotes); }, 250);
});
$('pinned-filter').addEventListener('change', () => { state.offset = 0; action(loadNotes); });
$('previous').addEventListener('click', () => { state.offset = Math.max(0, state.offset - state.limit); action(loadNotes); });
$('next').addEventListener('click', () => { state.offset += state.limit; action(loadNotes); });
$('export').addEventListener('click', () => action(async () => {
  const { data } = await api('/api/notes/export');
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'notes.json';
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  notice('Your notes have been exported.');
}, $('export')));
$('logout').addEventListener('click', () => action(async () => {
  if (!mayDiscard()) return;
  await api('/api/logout', { method: 'POST' });
  leaveNotebook();
  notice('Logged out.');
}, $('logout')));

// A harmless endpoint makes the request limit visible without exhausting login attempts.
$('rate-demo').addEventListener('click', () => action(async () => {
  let accepted = 0;
  let limited = 0;
  let wait = 0;
  for (let index = 0; index < 5; index++) {
    try { await api('/api/rate-limit-demo', { authenticated: false }); accepted++; }
    catch (error) {
      if (error.status !== 429) throw error;
      limited++;
      wait = Math.max(wait, error.retryAfter);
    }
  }
  $('rate-result').textContent = `${accepted} accepted; ${limited} limited (HTTP 429).${wait ? ` Try again in ${wait} seconds.` : ''}`;
}, $('rate-demo')));

// The browser sends the HttpOnly cookie automatically; JS never reads its value.
restoreNotebook();
