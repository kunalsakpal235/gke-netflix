import Fastify from 'fastify';
const app = Fastify({ logger: true });
const PORT = process.env.PORT || 8080;
const CATALOG = process.env.CATALOG_URL || 'http://catalog-service';
const PLAYBACK = process.env.PLAYBACK_URL || 'http://playback-service';

app.get('/healthz', async () => ({ status: 'ok' }));
app.get('/readyz', async () => ({ status: 'ready' }));

// Aggregates the catalog; forwards auth header downstream.
// Supports optional ?category= and ?q= query params, passed straight through to catalog-service.
app.get('/api/titles', async (req, reply) => {
  try {
    const qs = new URLSearchParams(req.query).toString();
    const r = await fetch(`${CATALOG}/titles${qs ? '?' + qs : ''}`, { headers: { authorization: req.headers.authorization || '' } });
    return await r.json();
  } catch (e) {
    reply.code(502); return { error: 'catalog unavailable' };
  }
});

app.get('/api/titles/:id', async (req, reply) => {
  try {
    const r = await fetch(`${CATALOG}/titles/${req.params.id}`, { headers: { authorization: req.headers.authorization || '' } });
    if (r.status === 404) { reply.code(404); return { error: 'title not found' }; }
    return await r.json();
  } catch (e) {
    reply.code(502); return { error: 'catalog unavailable' };
  }
});

app.get('/api/categories', async (req, reply) => {
  try {
    const r = await fetch(`${CATALOG}/categories`, { headers: { authorization: req.headers.authorization || '' } });
    return await r.json();
  } catch (e) {
    reply.code(502); return { error: 'catalog unavailable' };
  }
});

app.get('/api/play/:id', async (req, reply) => {
  try {
    const r = await fetch(`${PLAYBACK}/play/${req.params.id}`, { headers: { authorization: req.headers.authorization || '' } });
    if (r.status === 404) { reply.code(404); return { error: 'no video for that title' }; }
    return await r.json();
  } catch (e) {
    reply.code(502); return { error: 'playback service unavailable' };
  }
});

app.listen({ host: '0.0.0.0', port: PORT });
