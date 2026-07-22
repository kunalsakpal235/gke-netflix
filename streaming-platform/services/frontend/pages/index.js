export async function getServerSideProps() {
  const base = process.env.GATEWAY_URL || 'http://api-gateway';
  let titles = [];
  try { titles = await (await fetch(`${base}/api/titles`)).json(); } catch (e) {}
  return { props: { titles } };
}
export default function Home({ titles }) {
  return (<main style={{fontFamily:'sans-serif',padding:24}}>
    <h1>Streaming</h1>
    <ul>{(titles||[]).map(t => <li key={t.id}>{t.name}</li>)}</ul>
  </main>);
}
