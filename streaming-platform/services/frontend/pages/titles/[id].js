import Link from 'next/link';
import Layout from '../../components/Layout';

export async function getServerSideProps({ params }) {
  const base = process.env.GATEWAY_URL || 'http://api-gateway';
  let title = null;
  let videoUrl = null;
  let categories = [];
  try {
    const titleRes = await fetch(`${base}/api/titles/${params.id}`);
    if (titleRes.ok) title = await titleRes.json();
    const playRes = await fetch(`${base}/api/play/${params.id}`);
    if (playRes.ok) videoUrl = (await playRes.json()).videoUrl;
    categories = await (await fetch(`${base}/api/categories`)).json();
  } catch (e) {}
  return { props: { title, videoUrl, categories: categories || [] } };
}

export default function TitleDetail({ title, videoUrl, categories }) {
  if (!title) {
    return (
      <Layout categories={categories}>
        <div className="content">
          <p>Title not found.</p>
          <Link href="/">Back to browse</Link>
        </div>
      </Layout>
    );
  }
  return (
    <Layout categories={categories} activeCategory={title.category}>
      <div className="content">
        <Link href="/" className="back">&larr; Back to browse</Link>
        <div className="player">
          {videoUrl
            ? <video controls poster={title.thumbnail} src={videoUrl} />
            : <p className="unavailable">Video unavailable for this title.</p>}
        </div>
        <h1>{title.title}</h1>
        <div className="meta">
          <span className="badge">{title.category}</span>
          <span className="studio">{title.studio}</span>
        </div>
        <p className="description">{title.description}</p>
      </div>
      <style jsx>{`
        .content { padding: 24px 32px; max-width: 900px; margin: 0 auto; font-family: system-ui, -apple-system, sans-serif; }
        .back { display: inline-block; margin-bottom: 16px; color: #555; text-decoration: none; }
        .player { background: #000; border-radius: 8px; overflow: hidden; margin-bottom: 20px; }
        .player video { width: 100%; display: block; max-height: 500px; }
        .unavailable { color: #ccc; padding: 60px; text-align: center; }
        h1 { margin: 0 0 8px; }
        .meta { display: flex; gap: 12px; align-items: center; margin-bottom: 16px; }
        .badge { font-size: 12px; background: #eee; color: #555; padding: 2px 10px; border-radius: 10px; }
        .studio { color: #777; font-size: 14px; }
        .description { line-height: 1.6; color: #333; }
      `}</style>
    </Layout>
  );
}
