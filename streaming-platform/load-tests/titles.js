import http from 'k6/http';
import { check, sleep } from 'k6';
export const options = {
  stages: [ { duration: '1m', target: 50 }, { duration: '3m', target: 200 }, { duration: '1m', target: 0 } ],
  thresholds: { http_req_duration: ['p(95)<500'], http_req_failed: ['rate<0.01'] },
};
export default function () {
  const res = http.get(`${__ENV.BASE_URL}/api/titles`);
  check(res, { 'status 200': (r) => r.status === 200 });
  sleep(1);
}
