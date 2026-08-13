export default function Healthz() { return null; }
export function getServerSideProps({ res }) {
  res.statusCode = 200;
  res.end('ok');
  return { props: {} };
}
