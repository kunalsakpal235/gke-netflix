import Link from 'next/link';
import Layout from '../components/Layout';

export async function getServerSideProps({ query }) {
  const base = process.env.GATEWAY_URL || 'http://api-gateway';
  let titles = [];
  let categories = [];
  try {
    const params = new URLSearchParams();
    if (query.category) params.set('category', query.category);
    if (query.q) params.set('q', query.q);
    const qs = params.toString();
    titles = await (await fetch(`${base}/api/titles${qs ? '?' + qs : ''}`)).json();
    categories = await (await fetch(`${base}/api/categories`)).json();
  } catch (e) {}
  return { props: { titles: titles || [], categories: categories || [], activeCategory: query.category || null, q: query.q || null } };
}

export default function Home({ titles, categories, activeCategory, q }) {
  return (
    <Layout categories={categories} activeCategory={activeCategory}>
      <div className="content">
        <h1>{q ? `Results for "${q}"` : activeCategory ? activeCategory : 'Browse'}</h1>
        {titles.length === 0 && <p className="empty">No titles found.</p>}
        <div className="grid">
          {titles.map(t => (
            <Link href={`/titles/${t.id}`} key={t.id} className="card">
              <img src={t.thumbnail} alt={t.title} />
              <div className="card-body">
                <h3>{t.title}</h3>
                <span className="badge">{t.category}</span>
              </div>
            </Link>
          ))}
        </div>
      </div>
      <style jsx>{`
        .content { padding: 24px 32px; font-family: system-ui, -apple-system, sans-serif; }
        h1 { margin: 0 0 20px; }
        .empty { color: #777; }
        .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 20px; }
        .card { display: block; text-decoration: none; color: inherit; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,0.15); transition: transform 0.15s; }
        .card:hover { transform: translateY(-4px); }
        .card img { width: 100%; height: 140px; object-fit: cover; display: block; background: #ddd; }
        .card-body { padding: 12px; }
        .card-body h3 { margin: 0 0 6px; font-size: 15px; }
        .badge { font-size: 11px; background: #eee; color: #555; padding: 2px 8px; border-radius: 10px; }
      `}</style>
    </Layout>
  );
}
