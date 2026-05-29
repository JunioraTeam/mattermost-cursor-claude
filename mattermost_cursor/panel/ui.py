"""Single-page admin panel HTML (port of panel/ui.ts), served at GET /."""
from __future__ import annotations

PANEL_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>mattermost-cursor</title>
  <style>
    :root { --bg:#0f1419; --surface:#1a2332; --border:#2d3a4f; --text:#e7ecf3; --muted:#8b9cb3; --accent:#4c9aff; --ok:#3ecf8e; --err:#f87171; --warn:#fbbf24; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:system-ui,sans-serif; background:var(--bg); color:var(--text); min-height:100vh; }
    .wrap { max-width:1100px; margin:0 auto; padding:1.5rem; }
    h1 { font-size:1.25rem; font-weight:600; margin:0 0 1rem; }
    .card { background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:1.25rem; margin-bottom:1rem; }
    label { display:block; font-size:0.85rem; color:var(--muted); margin-bottom:0.35rem; }
    input { width:100%; padding:0.55rem 0.65rem; border:1px solid var(--border); border-radius:6px; background:var(--bg); color:var(--text); margin-bottom:0.75rem; }
    button { background:var(--accent); color:#fff; border:none; border-radius:6px; padding:0.55rem 1rem; font-weight:500; cursor:pointer; }
    button.secondary { background:transparent; border:1px solid var(--border); color:var(--muted); }
    .err { color:var(--err); font-size:0.9rem; margin-top:0.5rem; }
    .tabs { display:flex; gap:0.5rem; margin-bottom:1rem; }
    .tabs button.active { background:var(--surface); border:1px solid var(--accent); color:var(--accent); }
    table { width:100%; border-collapse:collapse; font-size:0.875rem; }
    th,td { text-align:left; padding:0.5rem 0.65rem; border-bottom:1px solid var(--border); vertical-align:top; }
    th { color:var(--muted); font-weight:500; }
    .badge { display:inline-block; padding:0.15rem 0.45rem; border-radius:4px; font-size:0.75rem; font-weight:500; }
    .badge.running { background:rgba(76,154,255,0.2); color:var(--accent); }
    .badge.completed { background:rgba(62,207,142,0.2); color:var(--ok); }
    .badge.error { background:rgba(248,113,113,0.2); color:var(--err); }
    .badge.cancelled,.badge.queued { background:rgba(251,191,36,0.15); color:var(--warn); }
    .muted { color:var(--muted); font-size:0.8rem; }
    .toolbar { display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem; }
    .hidden { display:none !important; }
    .preview { max-width:280px; word-break:break-word; }
    .user-block { margin-bottom:1.25rem; padding-bottom:1rem; border-bottom:1px solid var(--border); }
    .user-block h3 { margin:0 0 0.35rem; font-size:1rem; }
    .event { font-size:0.8rem; color:var(--muted); margin:0.25rem 0; }
  </style>
</head>
<body>
  <div class="wrap">
    <div id="login-view" class="card" style="max-width:360px;margin:4rem auto;">
      <h1>Sign in</h1>
      <label for="user">Username</label>
      <input id="user" autocomplete="username" />
      <label for="pass">Password</label>
      <input id="pass" type="password" autocomplete="current-password" />
      <button type="button" id="login-btn">Sign in</button>
      <p id="login-err" class="err hidden"></p>
    </div>
    <div id="app-view" class="hidden">
      <div class="toolbar">
        <h1>mattermost-cursor</h1>
        <div>
          <span class="muted" id="updated"></span>
          <button type="button" class="secondary" id="logout-btn" style="margin-left:0.5rem">Log out</button>
        </div>
      </div>
      <div class="tabs">
        <button type="button" class="active" data-tab="runs">Runs</button>
        <button type="button" data-tab="users">Users</button>
      </div>
      <div id="tab-runs" class="card">
        <table>
          <thead><tr><th>Status</th><th>User</th><th>Source</th><th>Started</th><th>Finished</th><th>Message</th></tr></thead>
          <tbody id="runs-body"></tbody>
        </table>
      </div>
      <div id="tab-users" class="card hidden"><div id="users-body"></div></div>
    </div>
  </div>
  <script>
    const $ = (id) => document.getElementById(id);
    let activeTab = 'runs';
    async function api(path, opts) {
      const res = await fetch(path, { credentials: 'same-origin', ...opts });
      if (res.status === 401) { $('login-view').classList.remove('hidden'); $('app-view').classList.add('hidden'); throw new Error('unauthorized'); }
      return res;
    }
    async function trySession() {
      try {
        const res = await api('/api/runs');
        if (res.ok) { $('login-view').classList.add('hidden'); $('app-view').classList.remove('hidden'); await refresh(); return true; }
      } catch {}
      return false;
    }
    $('login-btn').onclick = async () => {
      $('login-err').classList.add('hidden');
      const res = await fetch('/api/login', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: $('user').value, password: $('pass').value }) });
      if (!res.ok) { $('login-err').textContent = 'Invalid username or password'; $('login-err').classList.remove('hidden'); return; }
      $('login-view').classList.add('hidden'); $('app-view').classList.remove('hidden'); await refresh();
    };
    $('logout-btn').onclick = async () => { await fetch('/api/logout', { method: 'POST', credentials: 'same-origin' }); $('app-view').classList.add('hidden'); $('login-view').classList.remove('hidden'); };
    document.querySelectorAll('.tabs button').forEach((btn) => {
      btn.onclick = () => {
        activeTab = btn.dataset.tab;
        document.querySelectorAll('.tabs button').forEach((b) => b.classList.toggle('active', b === btn));
        $('tab-runs').classList.toggle('hidden', activeTab !== 'runs');
        $('tab-users').classList.toggle('hidden', activeTab !== 'users');
      };
    });
    function fmtTime(iso) { return iso ? new Date(iso).toLocaleString() : '\\u2014'; }
    function esc(s) { const d = document.createElement('div'); d.textContent = s ?? ''; return d.innerHTML; }
    async function refresh() {
      const [runsRes, usersRes] = await Promise.all([api('/api/runs'), api('/api/users')]);
      const runs = await runsRes.json();
      const users = await usersRes.json();
      $('runs-body').innerHTML = runs.length ? runs.map((r) => '<tr><td><span class="badge '+esc(r.status)+'">'+esc(r.status)+'</span></td><td>'+esc(r.username||r.userId)+'</td><td>'+esc(r.source)+'</td><td class="muted">'+fmtTime(r.startedAt)+'</td><td class="muted">'+fmtTime(r.finishedAt)+'</td><td class="preview">'+esc(r.messagePreview)+(r.detail?'<br><span class="muted">'+esc(r.detail)+'</span>':'')+'</td></tr>').join('') : '<tr><td colspan="6" class="muted">No runs yet</td></tr>';
      $('users-body').innerHTML = users.length ? users.map((u) => '<div class="user-block"><h3>@'+esc(u.username||u.userId)+' <span class="muted">('+u.messageCount+' messages)</span></h3><p class="muted">First: '+fmtTime(u.firstSeenAt)+' \\u00b7 Last: '+fmtTime(u.lastSeenAt)+'</p>'+(u.events||[]).map((e) => '<div class="event">'+fmtTime(e.at)+' \\u00b7 '+esc(e.type)+(e.preview?' \\u2014 '+esc(e.preview):'')+'</div>').join('')+'</div>').join('') : '<p class="muted">No user activity yet</p>';
      $('updated').textContent = 'Updated ' + new Date().toLocaleTimeString();
    }
    trySession().then((ok) => { if (ok) setInterval(() => refresh().catch(() => {}), 10000); });
  </script>
</body>
</html>"""
