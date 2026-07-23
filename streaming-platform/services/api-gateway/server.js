import Fastify from 'fastify';
const app = Fastify({ logger: true });
const PORT = process.env.PORT || 8080;
const CATALOG = process.env.CATALOG_URL || 'http://catalog-service';

app.get('/healthz', async () => ({ status: 'ok' }));
app.get('/readyz', async () => ({ status: 'ready' }));

// Aggregates the catalog; forwards auth header downstream.
app.get('/api/titles', async (req, reply) => {
  try {
    const r = await fetch(`${CATALOG}/titles`, { headers: { authorization: req.headers.authorization || '' } });
    return await r.json();
  } catch (e) {
    reply.code(502); return { error: 'catalog unavailable' };
  }
});

app.listen({ host: '0.0.0.0', port: PORT });
