/**
 * Cloudflare Worker for the AI video search engine.
 *
 * Serves the static UI from public/ and exposes two API areas:
 *
 *   POST /api/transcribe  takes a short audio clip (webm/opus from
 *                         MediaRecorder) and returns its transcript, so voice
 *                         search works in browsers with no speech service.
 *
 *   /api/download,        proxied to the hosted downloader in DOWNLOAD_API.
 *   /download_file/...    Static hosting cannot run yt-dlp, so downloads are
 *                         handled by that separate service (downloader_service/
 *                         in this repo). Proxying them through the Worker keeps
 *                         the page same-origin: no CORS, no config in the page.
 */

const MAX_AUDIO_BYTES = 8 * 1024 * 1024;
const WHISPER_MODEL = '@cf/openai/whisper';

// Cloudflare hosts this model, so the website can make a real song with sung
// vocals without any local machine or tunnel. Billed per track (~$0.15).
const SONG_MODEL = 'minimax/music-2.6';
const MAX_LYRICS = 3400;

// Paths that belong to the download service rather than to assets.
const DOWNLOAD_ROUTES = [
  /^\/api\/download(?:\/[a-z0-9]+)?$/i,
  /^\/download_file\/[a-z0-9]+$/i,
];

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === '/api/transcribe') {
      return transcribe(request, env);
    }

    if (url.pathname === '/api/song') {
      return makeSong(request, env);
    }

    if (url.pathname === '/api/song-file') {
      return songFile(request, env, url);
    }

    if (DOWNLOAD_ROUTES.some((route) => route.test(url.pathname))) {
      return download(request, env, url);
    }

    return env.ASSETS.fetch(request);
  },
};

async function makeSong(request, env) {
  if (request.method !== 'POST') {
    return json({ error: 'Method not allowed' }, 405);
  }
  if (!env.AI) {
    return json({ error: 'Workers AI is not bound to this Worker' }, 503);
  }

  const body = await request.json().catch(() => ({}));
  const prompt = String(body.prompt || '').slice(0, 1900).trim();
  const lyrics = String(body.lyrics || '').slice(0, MAX_LYRICS).trim();
  if (!prompt) {
    return json({ error: 'No prompt provided' }, 400);
  }

  const input = {
    prompt,
    is_instrumental: lyrics.length === 0,
    lyrics_optimizer: lyrics.length === 0,
    format: 'mp3',
    sample_rate: 44100,
  };
  if (lyrics) input.lyrics = lyrics;

  let result;
  try {
    result = await env.AI.run(SONG_MODEL, input);
  } catch (err) {
    return json({ error: 'The song model rejected the request: ' + (err.message || 'unknown') }, 502);
  }

  const audioUrl = result && result.result && result.result.audio
    ? result.result.audio
    : (result && result.audio) || null;
  if (!audioUrl) {
    return json({ error: 'The song model returned no audio' }, 502);
  }

  // The audio lives on the provider's storage; it is proxied so the page gets
  // one same-origin file instead of a cross-origin link that may expire.
  return json({
    audio: '/api/song-file?u=' + encodeURIComponent(audioUrl),
    model: SONG_MODEL,
    instrumental: lyrics.length === 0,
  });
}

async function songFile(request, env, url) {
  const target = url.searchParams.get('u');
  if (!target) {
    return json({ error: 'No audio URL' }, 400);
  }
  let parsed;
  try {
    parsed = new URL(target);
  } catch (err) {
    return json({ error: 'Bad audio URL' }, 400);
  }
  // Only the model provider's own storage is fetched here, so this route cannot
  // be turned into an open proxy.
  const allowed = parsed.protocol === 'https:' && (
    parsed.hostname.endsWith('.aliyuncs.com') ||
    parsed.hostname === 'api.minimaxi.com'
  );
  if (!allowed) {
    return json({ error: 'That host is not allowed' }, 400);
  }

  const upstream = await fetch(parsed.toString());
  if (!upstream.ok) {
    return json({ error: 'Could not fetch the generated audio (' + upstream.status + ')' }, 502);
  }
  const headers = new Headers();
  headers.set('content-type', upstream.headers.get('content-type') || 'audio/mpeg');
  headers.set('cache-control', 'no-store');
  return new Response(upstream.body, { status: 200, headers });
}

async function download(request, env, url) {
  const base = String(env.DOWNLOAD_API || '').trim().replace(/\/+$/, '');
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
    return json({
      error: 'The download service could not be reached. It may be asleep or down.',
    }, 502);
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

async function transcribe(request, env) {
  if (request.method !== 'POST') {
    return json({ error: 'Method not allowed' }, 405);
  }
  if (!env.AI) {
    return json({ error: 'Workers AI is not bound to this Worker' }, 503);
  }

  const audio = await request.arrayBuffer();
  if (!audio.byteLength) {
    return json({ error: 'Empty audio' }, 400);
  }
  if (audio.byteLength > MAX_AUDIO_BYTES) {
    return json({ error: 'Clip too large' }, 413);
  }

  try {
    const result = await env.AI.run(WHISPER_MODEL, {
      audio: [...new Uint8Array(audio)],
    });
    const text = (result && (result.text || (result.transcription && result.transcription.text))) || '';
    return json({ text: String(text).trim() });
  } catch (err) {
    const message = err && err.message ? err.message : 'unknown error';
    return json({ error: 'Transcription failed: ' + message }, 502);
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
