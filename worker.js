/**
 * Cloudflare Worker for the AI video search engine.
 *
 * Serves the static UI from public/ and exposes one API route: POST
 * /api/transcribe takes a short audio clip (webm/opus from MediaRecorder) and
 * returns its transcript, so voice search works in browsers that have no
 * built-in speech service.
 */

const MAX_AUDIO_BYTES = 8 * 1024 * 1024;
const WHISPER_MODEL = '@cf/openai/whisper';

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === '/api/transcribe') {
      return transcribe(request, env);
    }

    return env.ASSETS.fetch(request);
  },
};

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
