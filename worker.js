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
      return searchIndex(env, url);
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
async function searchIndex(env, url) {
  const query = (url.searchParams.get('q') || '').trim().slice(0, 120);
  const limit = Math.min(60, Math.max(1, Number(url.searchParams.get('limit')) || 30));

  if (!env.DB) {
    return json({ error: 'No video index is attached to this Worker.' }, 501);
  }

  const library = await indexTotals(env);
  if (!query) {
    return json({ query: '', total: 0, library, videos: [] });
  }

  const terms = (query.toLowerCase().match(/[a-z0-9']+/g) || []).slice(0, 8);
  if (!terms.length) {
    return json({ query, total: 0, library, videos: [] });
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

  const counted = await env.DB.prepare(`SELECT COUNT(*) AS n FROM videos WHERE ${clause}`)
    .bind(...params)
    .first();

  const found = await env.DB.prepare(
    'SELECT url, title, description, thumbnail, duration, source, click_count, tags '
    + `FROM videos WHERE ${clause} `
    + 'ORDER BY click_count DESC, relevance_score DESC, id DESC LIMIT ?'
  ).bind(...params, limit).all();

  const videos = (found.results || []).map((row) => ({
    u: row.url,
    t: row.title,
    d: row.description,
    th: row.thumbnail,
    du: row.duration,
    s: row.source,
    c: row.click_count,
    tg: row.tags,
  }));

  // Only searches a person made are kept: log=1 is sent by the page, so a crawler
  // following the URL cannot fill the history with its own queries.
  if (url.searchParams.get('log') === '1') {
    try {
      await env.DB.prepare(
        'INSERT INTO search_history (query, result_count, searched_at) VALUES (?, ?, ?)'
      ).bind(query, Number(counted && counted.n) || videos.length, Date.now() / 1000).run();
      library.total_searches += 1;
    } catch (err) { /* a full or missing table must not fail the search */ }
  }

  return json({ query, total: Number(counted && counted.n) || 0, library, videos });
}

async function indexTotals(env) {
  try {
    const videos = await env.DB.prepare('SELECT COUNT(*) AS n FROM videos').first();
    const searches = await env.DB.prepare('SELECT COUNT(*) AS n FROM search_history').first();
    const clicks = await env.DB.prepare('SELECT COALESCE(SUM(click_count), 0) AS n FROM videos').first();
    return {
      total_videos: Number(videos && videos.n) || 0,
      total_searches: Number(searches && searches.n) || 0,
      total_clicks: Number(clicks && clicks.n) || 0,
    };
  } catch (err) {
    return { total_videos: 0, total_searches: 0, total_clicks: 0 };
  }
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
