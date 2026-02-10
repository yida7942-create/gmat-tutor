/**
 * GMAT Tutor - Cloudflare Worker AI Proxy
 *
 * Forwards AI API requests from the PWA (browser) to the target API server,
 * bypassing CORS restrictions. Supports streaming (SSE).
 *
 * Deploy: https://developers.cloudflare.com/workers/get-started/guide/
 */

// Allowed origins (update with your GitHub Pages URL)
const ALLOWED_ORIGINS = [
  'https://yida7942-create.github.io',
  'http://localhost:8080',
  'http://127.0.0.1:8080',
];

// Allowed API target hosts (prevent abuse as open proxy)
const ALLOWED_API_HOSTS = [
  'ark.cn-beijing.volces.com',
  'api.openai.com',
  'api.deepseek.com',
  'api.moonshot.cn',
];

function getCorsHeaders(request) {
  const origin = request.headers.get('Origin') || '';
  const allowed = ALLOWED_ORIGINS.find(o => origin.startsWith(o));
  return {
    'Access-Control-Allow-Origin': allowed || ALLOWED_ORIGINS[0],
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Target-URL',
    'Access-Control-Max-Age': '86400',
  };
}

export default {
  async fetch(request, env) {
    // Handle CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        status: 204,
        headers: getCorsHeaders(request),
      });
    }

    // Only allow POST (for chat completions)
    if (request.method !== 'POST') {
      return new Response(JSON.stringify({ error: 'Only POST is allowed' }), {
        status: 405,
        headers: { ...getCorsHeaders(request), 'Content-Type': 'application/json' },
      });
    }

    // Get the target API URL from the X-Target-URL header
    const targetUrl = request.headers.get('X-Target-URL');
    if (!targetUrl) {
      return new Response(JSON.stringify({ error: 'Missing X-Target-URL header' }), {
        status: 400,
        headers: { ...getCorsHeaders(request), 'Content-Type': 'application/json' },
      });
    }

    // Validate target host
    try {
      const targetHost = new URL(targetUrl).hostname;
      if (!ALLOWED_API_HOSTS.some(h => targetHost.endsWith(h))) {
        return new Response(JSON.stringify({ error: 'Target API host not allowed' }), {
          status: 403,
          headers: { ...getCorsHeaders(request), 'Content-Type': 'application/json' },
        });
      }
    } catch (e) {
      return new Response(JSON.stringify({ error: 'Invalid target URL' }), {
        status: 400,
        headers: { ...getCorsHeaders(request), 'Content-Type': 'application/json' },
      });
    }

    // Forward the request
    try {
      const body = await request.text();
      const apiResponse = await fetch(targetUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': request.headers.get('Authorization') || '',
        },
        body: body,
      });

      // Build response headers with CORS
      const responseHeaders = new Headers(getCorsHeaders(request));
      responseHeaders.set('Content-Type', apiResponse.headers.get('Content-Type') || 'application/json');

      // Support streaming responses (SSE)
      if (apiResponse.headers.get('Content-Type')?.includes('text/event-stream')) {
        responseHeaders.set('Content-Type', 'text/event-stream');
        responseHeaders.set('Cache-Control', 'no-cache');
        responseHeaders.set('Connection', 'keep-alive');

        return new Response(apiResponse.body, {
          status: apiResponse.status,
          headers: responseHeaders,
        });
      }

      // Non-streaming response
      const responseBody = await apiResponse.text();
      return new Response(responseBody, {
        status: apiResponse.status,
        headers: responseHeaders,
      });

    } catch (e) {
      return new Response(JSON.stringify({ error: `Proxy error: ${e.message}` }), {
        status: 502,
        headers: { ...getCorsHeaders(request), 'Content-Type': 'application/json' },
      });
    }
  },
};
