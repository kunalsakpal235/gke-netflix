export default function Readyz() { return null; }
export function getServerSideProps({ res }) {
  res.statusCode = 200;
  res.end('ready');
  return { props: {} };
}
