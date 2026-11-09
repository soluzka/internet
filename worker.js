/**
 * Cloudflare Worker for the video discovery site.
 *
 * This deployment is deliberately AI-free on Cloudflare's side: no Workers AI
 * binding, no hosted model calls. The AI in this project is the local one —
 * song_service/ runs the lyric and music models on your own GPU, and the page
 * talks to it directly (see public/config.js).
 *
 * What is left here is only what a static host cannot do for itself:
 *
 *   /api/download,        proxied to the hosted downloader in DOWNLOAD_API.
 *   /download_file/...    Static hosting cannot run yt-dlp, so downloads are
 *                         handled by that separate service (downloader_service/
 *                         in this repo). Proxying them through the Worker keeps
 *                         the page same-origin: no CORS, no config in the page.
 */

// Paths that belong to the download service rather than to assets.
const DOWNLOAD_ROUTES = [
  /^\/api\/download(?:\/[a-z0-9]+)?$/i,
  /^\/download_file\/[a-z0-9]+$/i,
];

// Speech-to-text runs here, on Cloudflare's Whisper, so voice search works from
// a browser whether or not anything is running on the visitor's machine. The
// clip never leaves Cloudflare's edge, and the free neuron allowance covers far
// more than a person can speak in a day.
const TRANSCRIBE_ROUTE = /^\/api\/transcribe$/i;

// Open this in a browser to see whether the download service is configured,
// awake and holding a cookie jar, instead of guessing from a failed download.
const HEALTH_ROUTE = /^\/api\/health$/i;

// The video index, answered from D1 instead of from the 3 MB videos.json the page
// used to download in full before it could show anything.
const SEARCH_ROUTE = /^\/api\/search$/i;

// One click on one video. This is how the library changes without a re-import:
// the count the cards are ordered by goes up, and the pair of query and video is
// kept in learned_preferences.
const CLICK_ROUTE = /^\/api\/click$/i;

// Videos found by the machine's own yt-dlp, handed up to be stored. YouTube is
// the reason this exists: a Worker's address is refused by YouTube, so the
// search that reaches it happens on the user's PC and only the result travels.
const INGEST_ROUTE = /^\/api\/ingest$/i;

// A short code that ties one person's saved search to several devices. There are
// no accounts on this site, and browser storage never leaves its own browser, so
// the code is the one thing that can travel: type it once on another device and
// the same saved search follows.
const SYNC_ROUTE = /^\/api\/sync$/i;

// The music model cannot run here: it needs a GPU that a Worker does not have.
// These paths exist so the page gets a straight answer instead of a 405 from
// the static asset handler, and so an address can be supplied with SONG_API
// when the model is reachable from the internet.
const SONG_ROUTES = [
  /^\/api\/lyrics$/i,
  /^\/api\/song$/i,
  /^\/api\/song\/[a-z0-9]+$/i,
  /^\/song_file\/[a-z0-9]+$/i,
  /^\/last_song$/i,
];
const WHISPER_MODEL = '@cf/openai/whisper-large-v3-turbo';
const MAX_CLIP_BYTES = 8 * 1024 * 1024;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (DOWNLOAD_ROUTES.some((route) => route.test(url.pathname))) {
      return download(request, env, url);
    }

    if (TRANSCRIBE_ROUTE.test(url.pathname)) {
      return transcribe(request, env);
    }

    if (HEALTH_ROUTE.test(url.pathname)) {
      return downloaderHealth(env);
    }

    if (SEARCH_ROUTE.test(url.pathname)) {
      try {
        return await cachedSearch(env, request, url);
      } catch (err) {
        // An uncaught throw here becomes a blank Cloudflare 500 with no clue in
        // it. The reason is worth more than the tidiness.
        return json({ error: String((err && err.message) || err) }, 500);
      }
    }

    if (CLICK_ROUTE.test(url.pathname)) {
      return recordClick(env, request);
    }

    if (INGEST_ROUTE.test(url.pathname)) {
      return ingestVideos(env, request);
    }

    if (SYNC_ROUTE.test(url.pathname)) {
      return syncSession(env, request, url);
    }

    if (SONG_ROUTES.some((route) => route.test(url.pathname))) {
      return song(request, env, url);
    }

    return env.ASSETS.fetch(request);
  },
};

async function song(request, env, url) {
  const base = String(env.SONG_API || '').trim().replace(/\/+$/, '');
  if (!base) {
    return json({
      error: 'The music model runs on the computer that has the GPU. Start the desktop app '
        + 'there so the page can use it, or set SONG_API to an address that reaches it.',
      model: null,
    }, 501);
  }

  const init = { method: request.method, headers: { accept: request.headers.get('accept') || '*/*' } };
  const contentType = request.headers.get('content-type');
  if (contentType) init.headers['content-type'] = contentType;
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    init.body = await request.arrayBuffer();
  }

  try {
    const upstream = await fetch(base + url.pathname + url.search, init);
    const headers = new Headers(upstream.headers);
    headers.delete('access-control-allow-origin');
    headers.delete('transfer-encoding');
    headers.delete('connection');
    return new Response(upstream.body, { status: upstream.status, headers });
  } catch (err) {
    return json({ error: 'The song service at that address did not answer.' }, 502);
  }
}

function downloadBase(env) {
  return String(env.DOWNLOAD_API || '').trim().replace(/\/+$/, '');
}

async function downloaderHealth(env) {
  const base = downloadBase(env);
  if (!base) {
    return json({
      configured: false,
      error: 'Set DOWNLOAD_API to the URL of the downloader service.',
    }, 200);
  }
  try {
    const upstream = await fetch(base + '/health', { headers: { accept: 'application/json' } });
    const body = await upstream.json().catch(() => ({}));
    return json({
      configured: true,
      url: base,
      reachable: upstream.ok,
      status: upstream.status,
      downloader: body,
    }, 200);
  } catch (err) {
    return json({
      configured: true,
      url: base,
      reachable: false,
      error: 'The download service did not answer. Free instances sleep when idle: '
        + 'open this again in a minute, or open the service URL directly to wake it.',
    }, 200);
  }
}

async function download(request, env, url) {
  const base = downloadBase(env);
  if (!base) {
    return json({
      error: 'No downloader is set up for this deployment yet. ' +
        'Set DOWNLOAD_API to the URL of the downloader service.',
    }, 503);
  }

  const init = { method: request.method, headers: {}, redirect: 'follow' };
  const contentType = request.headers.get('content-type');
  if (contentType) init.headers['content-type'] = contentType;
  // Bodies here are small JSON documents; reading them avoids streaming a
  // request body through a second fetch.
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    init.body = await request.text();
  }

  let upstream;
  try {
    upstream = await fetch(base + url.pathname + url.search, init);
  } catch (err) {
    // Say which of the two it is: a sleeping free instance comes back on its own,
    // a wrong URL never will.
    let detail = 'It may be asleep or down.';
    try {
      const ping = await fetch(base + '/health', { headers: { accept: 'application/json' } });
      if (ping.ok) detail = 'It answered a health check just now, so try the download again.';
    } catch (ignored) {
      detail = 'Its health check did not answer either, so it is asleep or the URL is wrong.';
    }
    return json({ error: 'The download service could not be reached. ' + detail }, 502);
  }

  // Pass the service's answer straight through, headers included, so the file's
  // Content-Disposition still makes the browser save it.
  const headers = new Headers(upstream.headers);
  headers.delete('access-control-allow-origin');
  headers.delete('access-control-allow-credentials');
  // Hop-by-hop headers belong to the upstream connection, not to this response.
  headers.delete('transfer-encoding');
  headers.delete('connection');
  return new Response(upstream.body, { status: upstream.status, headers });
}

// Workers AI takes the audio as base64 text, and the clip is small (a few
// seconds of webm), so the whole thing is converted in one pass.
function toBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

async function transcribe(request, env) {
  if (request.method === 'OPTIONS') return new Response(null, { status: 204 });
  if (request.method !== 'POST') {
    return json({ error: 'Send the recording as a POST body.' }, 405);
  }

  const audio = await request.arrayBuffer();
  if (!audio || audio.byteLength < 800) {
    return json({ error: 'The recording was empty.' }, 400);
  }
  if (audio.byteLength > MAX_CLIP_BYTES) {
    return json({ error: 'That recording is too long to transcribe.' }, 413);
  }

  let result;
  try {
    result = await env.AI.run(WHISPER_MODEL, { audio: toBase64(audio) });
  } catch (err) {
    return json({ error: 'The speech service could not transcribe that clip.' }, 502);
  }

  const text = String((result && result.text) || '').trim();
  return json({ text, model: WHISPER_MODEL });
}

// The video index, queried in place. Every word of the query has to appear in the
// row, so "dubstep mix" narrows instead of widening to anything holding either
// word, and the order prefers what people actually clicked.
//
// The page asks for thirty at a time and paints more as it scrolls; before this
// it downloaded all 8,724 rows before it could show a single card.
// The same words searched again within a minute - a retry, a voice repeat, a
// reload - are answered from the edge cache instead of scanning the database
// again. A search that logs itself, or one that discovers new videos, has a side
// effect and is never cached.
async function cachedSearch(env, request, url) {
  const plain = request.method === 'GET'
    && url.searchParams.get('log') !== '1'
    && url.searchParams.get('discover') !== '1';
  if (!plain) return searchIndex(env, url);

  const cache = caches.default;
  const key = new Request('https://search-cache.internal' + url.pathname + url.search, { method: 'GET' });
  const hit = await cache.match(key);
  if (hit) return hit;

  const fresh = await searchIndex(env, url);
  if (fresh.status === 200) {
    const copy = new Response(fresh.body, {
      status: fresh.status,
      statusText: fresh.statusText,
      headers: fresh.headers,
    });
    copy.headers.set('Cache-Control', 'public, max-age=60');
    await cache.put(key, copy).catch(() => {});
  }
  return fresh;
}

async function searchIndex(env, url) {
  const query = (url.searchParams.get('q') || '').trim().slice(0, 120);
  // 200 a page, not 60: a query with 332 matches used to say "332 matches" and
  // show sixty of them, because that is all one request returned.
  const limit = Math.min(200, Math.max(1, Number(url.searchParams.get('limit')) || 30));
  const offset = Math.max(0, Number(url.searchParams.get('offset')) || 0);

  if (!env.DB) {
    return json({ error: 'No video index is attached to this Worker.' }, 501);
  }

  if (!query) {
    return json({ query: '', total: 0, library: await indexTotals(env), discovered: 0, videos: [] });
  }

  // A search is also how the library grows. Before counting, this asks
  // Dailymotion's public API for the same words and inserts only the videos the
  // table has never seen - so searching something new leaves the library larger
  // than it was, which is what a discovery tool is for.
  let discovered = 0;
  if (url.searchParams.get('discover') === '1') {
    discovered = await discoverVideos(env, query);
  }
  const library = await indexTotals(env);

  const terms = (query.toLowerCase().match(/[a-z0-9']+/g) || []).slice(0, 8);
  if (!terms.length) {
    return json({ query, total: 0, library, discovered, videos: [] });
  }

  // LIKE wildcards inside a search term are escaped, so a term of "100%" is a
  // search for that text rather than for everything.
  const patterns = terms.map((term) => '%' + term.replace(/[\\%_]/g, (ch) => '\\' + ch) + '%');
  const clause = patterns
    .map(() => "(lower(title) LIKE ? ESCAPE '\\' OR lower(description) LIKE ? ESCAPE '\\' "
      + "OR lower(tags) LIKE ? ESCAPE '\\')")
    .join(' AND ');
  const params = [];
  patterns.forEach((pattern) => params.push(pattern, pattern, pattern));

  // Counting the matches is a full scan of the library (LIKE on three columns),
  // so it is done once, on the first page. Pages after it only need rows: the
  // page keeps the total from page one, and asking for it again on every one of
  // four paged requests was four scans for one search.
  // Counting every match is a scan of the whole library, and it was the single
  // biggest reader in the app: one "dubstep" search read 8,756 rows just to print
  // "328 matches". Capping the inner scan at 1000 rows keeps the number exact for
  // every ordinary search and costs far less, which is what stops the free daily
  // limit from running out in a day of browsing.
  const counted = offset > 0
    ? null
    : await env.DB.prepare(
      `SELECT COUNT(*) AS n FROM (SELECT 1 FROM videos WHERE ${clause} LIMIT 1000)`
    ).bind(...params).first();

  const found = await env.DB.prepare(
    'SELECT url, title, description, thumbnail, duration, source, click_count, tags, genre_json '
    + `FROM videos WHERE ${clause} `
    + 'ORDER BY click_count DESC, relevance_score DESC, id DESC LIMIT ? OFFSET ?'
  ).bind(...params, limit, offset).all();

  const videos = (found.results || []).map((row) => ({
    u: row.url,
    t: row.title,
    d: row.description,
    th: row.thumbnail,
    du: row.duration,
    s: row.source,
    c: row.click_count,
    tg: row.tags,
    // The inferred genre, as the JSON export carries it: {n: name, c: confidence}.
    // It is the one column the database did not already have.
    g: parseGenre(row.genre_json),
  }));

  // Only searches a person made are kept: log=1 is sent by the page, so a crawler
  // following the URL cannot fill the history with its own queries.
  if (url.searchParams.get('log') === '1') {
    try {
      await env.DB.batch([
        env.DB.prepare(
          'INSERT INTO search_history (query, result_count, searched_at) VALUES (?, ?, ?)'
        ).bind(query, Number(counted && counted.n) || videos.length, Date.now() / 1000),
        bumpStats(env, 'total_searches', 1),
      ]);
      library.total_searches += 1;
    } catch (err) { /* a full or missing table must not fail the search */ }
  }  return json({
    query,
    total: counted ? (Number(counted.n) || 0) : Number(videos.length) + offset,
    library,
    discovered,
    videos,
  });
}

// Dailymotion's public API answers without a key or an account, and the library
// is already mostly Dailymotion, so the thumbnails, durations and URLs arrive in
// the same shape the existing rows use.
const DISCOVER_API = 'https://api.dailymotion.com/videos';

async function discoverVideos(env, query, limit = 20) {
  let doc;
  try {
    const api = DISCOVER_API
      + '?search=' + encodeURIComponent(query)
      + '&fields=id,title,url,description,thumbnail_360_url,duration'
      + '&sort=relevance&limit=' + limit;
    const response = await fetch(api, { headers: { accept: 'application/json' } });
    if (!response.ok) return 0;
    doc = await response.json();
  } catch (err) {
    return 0;   // discovery failing must never fail the search
  }

  const found = Array.isArray(doc && doc.list) ? doc.list : [];
  if (!found.length) return 0;

  const statements = [];
  const seen = new Set();
  for (const row of found) {
    const link = String(row.url || '').trim();
    const title = String(row.title || '').trim();
    if (!link || !title || seen.has(link)) continue;
    seen.add(link);
    statements.push(
      env.DB.prepare(
        'INSERT OR IGNORE INTO videos '
        + '(url, title, description, thumbnail, duration, source, platform, discovered_at, '
        + ' click_count, relevance_score, tags) '
        + "VALUES (?, ?, ?, ?, ?, 'Dailymotion', 'Dailymotion', ?, 0, 0, '')"
      ).bind(
        link,
        title.slice(0, 300),
        String(row.description || '').slice(0, 2000),
        String(row.thumbnail_360_url || ''),
        formatSeconds(row.duration),
        Date.now() / 1000
      )
    );
  }
  if (!statements.length) return 0;

  // meta.changes counts the rows INSERT OR IGNORE actually wrote: a video the
  // library already had is ignored and not counted as new.
  let added = 0;
  try {
    const results = await env.DB.batch(statements);
    for (const result of results) {
      added += Number((result.meta && result.meta.changes) || 0);
    }
  } catch (err) {
    return 0;
  }
  return added;
}

function formatSeconds(value) {
  const total = Math.round(Number(value) || 0);
  if (!total) return 'Unknown';
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return minutes + ':' + String(seconds).padStart(2, '0');
}

async function syncSession(env, request, url) {
  if (request.method === 'OPTIONS') return new Response(null, { status: 204 });
  if (!env.DB) return json({ error: 'No video index is attached to this Worker.' }, 501);

  // Codes are shown to people, so they stay short and typable: letters, digits
  // and dashes only.
  const code = String(url.searchParams.get('code') || '')
    .toUpperCase()
    .replace(/[^A-Z0-9-]/g, '')
    .slice(0, 12);
  if (code.length < 4) return json({ error: 'A sync code is needed.' }, 400);

  if (request.method === 'GET') {
    try {
      const row = await env.DB.prepare(
        'SELECT payload, updated_at FROM sync_sessions WHERE code = ?'
      ).bind(code).first();
      return json({
        code,
        payload: row ? row.payload : null,
        updated_at: row ? Number(row.updated_at) || 0 : 0,
      });
    } catch (err) {
      return json({ error: 'The saved search could not be read.' }, 503);
    }
  }

  if (request.method === 'POST') {
    const body = await request.json().catch(() => null);
    const payload = body && typeof body.payload === 'string' ? body.payload : '';
    if (!payload) return json({ error: 'There was nothing to save.' }, 400);
    try {
      await env.DB.prepare(
        'INSERT INTO sync_sessions (code, payload, updated_at) VALUES (?, ?, ?) '
        + 'ON CONFLICT(code) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at'
      ).bind(code, payload.slice(0, 200000), Date.now()).run();
      return json({ ok: true, code });
    } catch (err) {
      return json({
        error: 'The search could not be saved to the server.',
        detail: String((err && err.message) || err).slice(0, 200),
      }, 503);
    }
  }

  return json({ error: 'Only reading and saving are supported here.' }, 405);
}

async function ingestVideos(env, request) {
  if (request.method === 'OPTIONS') return new Response(null, { status: 204 });
  if (request.method !== 'POST') {
    return json({ error: 'Send the videos as a POST body.' }, 405);
  }
  if (!env.DB) {
    return json({ error: 'No video index is attached to this Worker.' }, 501);
  }

  const body = await request.json().catch(() => null);
  const list = Array.isArray(body && body.videos) ? body.videos.slice(0, 40) : [];
  if (!list.length) {
    return json({ error: 'No videos were given.' }, 400);
  }

  const statements = [];
  const seen = new Set();
  for (const video of list) {
    const link = String((video && video.url) || '').trim();
    const title = String((video && video.title) || '').trim();
    if (!/^https?:\/\//.test(link) || !title || seen.has(link)) continue;
    seen.add(link);
    const source = String((video.source) || 'YouTube').slice(0, 40);
    statements.push(
      env.DB.prepare(
        'INSERT OR IGNORE INTO videos '
        + '(url, title, description, thumbnail, duration, source, platform, discovered_at, '
        + ' click_count, relevance_score, tags) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, \'\')'
      ).bind(
        link,
        title.slice(0, 300),
        String(video.description || '').slice(0, 2000),
        String(video.thumbnail || ''),
        String(video.duration || 'Unknown'),
        source,
        source,
        Date.now() / 1000
      )
    );
  }
  if (!statements.length) {
    return json({ added: 0, library: await indexTotals(env) });
  }

  let added = 0;
  try {
    const results = await env.DB.batch(statements);
    for (const result of results) added += Number((result.meta && result.meta.changes) || 0);
    if (added) await bumpStats(env, 'total_videos', added).run();
  } catch (err) {
    // The reason is useful: a full disk, a locked table and an exhausted daily
    // limit all look identical from the page otherwise.
    return json({
      error: 'Those videos could not be stored.',
      detail: String((err && err.message) || err).slice(0, 300),
    }, 500);
  }
  return json({ added, library: await indexTotals(env) });
}

async function recordClick(env, request) {
  if (request.method === 'OPTIONS') return new Response(null, { status: 204 });
  if (request.method !== 'POST') {
    return json({ error: 'Send the click as a POST body.' }, 405);
  }
  if (!env.DB) {
    return json({ error: 'No video index is attached to this Worker.' }, 501);
  }

  const body = await request.json().catch(() => null);
  const videoUrl = String((body && body.url) || '').trim().slice(0, 400);
  if (!videoUrl) {
    return json({ error: 'No video was given.' }, 400);
  }
  const title = String((body && body.title) || '').slice(0, 300);
  const query = String((body && body.query) || '').slice(0, 120);

  try {
    await env.DB.batch([
      env.DB.prepare('UPDATE videos SET click_count = click_count + 1 WHERE url = ?').bind(videoUrl),
      env.DB.prepare(
        'INSERT INTO learned_preferences (query, clicked_url, clicked_title, learned_at) VALUES (?, ?, ?, ?)'
      ).bind(query, videoUrl, title, Date.now() / 1000),
      bumpStats(env, 'total_clicks', 1),
    ]);
  } catch (err) {
    // A click is worth keeping even when the database cannot take it yet: the
    // page holds it in the browser and sends it again later. Answering 500 lost
    // the click and made the counters stand still while D1 was over its limit.
    return json({ ok: false, queued: true, library: null });
  }

  return json({ ok: true, library: await indexTotals(env) });
}

function parseGenre(text) {
  if (!text) return null;
  try {
    const parsed = JSON.parse(text);
    return parsed && parsed.n ? parsed : null;
  } catch (err) {
    return null;
  }
}

// The three counters used to be three full-table aggregates: COUNT over the
// videos, COUNT over the history, and SUM over every click_count. On a library
// of 8,756 rows that is about 17,500 rows read every single time the page asked
// for its numbers - and the counters are read on page load, on every search and
// again after every click. That is what exhausted D1's free daily row-read limit
// and made the page show zeroes and the search answer 500. One row now holds the
// totals, and the write paths keep it current.
async function indexTotals(env) {
  if (!env.DB) return { total_videos: 0, total_searches: 0, total_clicks: 0 };
  try {
    const row = await env.DB.prepare(
      'SELECT total_videos, total_searches, total_clicks FROM library_stats WHERE id = 1'
    ).first();
    return {
      total_videos: Number(row && row.total_videos) || 0,
      total_searches: Number(row && row.total_searches) || 0,
      total_clicks: Number(row && row.total_clicks) || 0,
    };
  } catch (err) {
    return { total_videos: 0, total_searches: 0, total_clicks: 0 };
  }
}

// Keeps the counters honest without ever scanning the table again.
function bumpStats(env, field, amount) {
  if (!env.DB) return null;
  return env.DB.prepare(`UPDATE library_stats SET ${field} = ${field} + ? WHERE id = 1`)
    .bind(amount);
}

function json(body, status) {
  return new Response(JSON.stringify(body), {
    status: status || 200,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
    },
  });
}
