import { useState } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';

export default function Layout({ categories = [], activeCategory, children }) {
  const router = useRouter();
  const [q, setQ] = useState(router.query.q || '');

  function onSearch(e) {
    e.preventDefault();
    router.push(q ? `/?q=${encodeURIComponent(q)}` : '/');
  }

  return (
    <div>
      <header className="nav">
        <Link href="/" className="brand">Streaming</Link>
        <nav className="tabs">
          <Link href="/" className={!activeCategory ? 'active' : ''}>All</Link>
          {categories.map(c => (
            <Link key={c} href={`/?category=${encodeURIComponent(c)}`} className={activeCategory === c ? 'active' : ''}>
              {c}
            </Link>
          ))}
        </nav>
        <form onSubmit={onSearch} className="search">
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search titles..." />
          <button type="submit">Search</button>
        </form>
      </header>
      <main>{children}</main>
      <style jsx>{`
        .nav {
          display: flex; align-items: center; gap: 24px;
          padding: 16px 32px; background: #141414; color: #fff;
          flex-wrap: wrap;
        }
        .brand { font-size: 22px; font-weight: 700; color: #e50914; text-decoration: none; }
        .tabs { display: flex; gap: 16px; flex: 1; }
        .tabs :global(a) { color: #ccc; text-decoration: none; font-size: 14px; padding: 4px 0; }
        .tabs :global(a.active) { color: #fff; border-bottom: 2px solid #e50914; }
        .tabs :global(a:hover) { color: #fff; }
        .search { display: flex; gap: 6px; }
        .search input { padding: 6px 10px; border-radius: 4px; border: none; }
        .search button { padding: 6px 12px; border-radius: 4px; border: none; background: #e50914; color: #fff; cursor: pointer; }
        main { min-height: 80vh; background: #f5f5f5; }
      `}</style>
    </div>
  );
}
