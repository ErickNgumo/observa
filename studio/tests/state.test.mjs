import test from 'node:test';
import assert from 'node:assert/strict';
import { upsert, number } from '../src/api.ts';

test('replayed SSE updates replace streamed items without duplicating history', () => {
  let items = [{ id: 'user', text: 'Research', created: 1 }, { id: 'reply', text: 'Part', created: 2 }];
  const complete = { id: 'reply', text: 'Partial response completed', created: 2, status: 'completed' };
  items = upsert(items, complete);
  items = upsert(items, complete);
  assert.deepEqual(items.map(i => i.id), ['user', 'reply']);
  assert.equal(items[1].text, complete.text);
  assert.equal(items[1].status, 'completed');
});

test('independent experiments keep their identities when results arrive out of order', () => {
  let jobs = upsert([], { id: 'a', status: 'running' });
  jobs = upsert(jobs, { id: 'b', status: 'completed' });
  jobs = upsert(jobs, { id: 'a', status: 'failed' });
  assert.deepEqual(jobs.map(j => [j.id, j.status]), [['a', 'failed'], ['b', 'completed']]);
});

test('unavailable canonical metrics never become invented zeroes', () => {
  for (const value of [null, undefined, NaN, Infinity, 'not available']) assert.equal(number(value), '—');
  assert.equal(number(0), '0');
  assert.equal(number(-12.5), '-12.5');
  assert.notEqual(number(0.00199979), '0');
  assert.notEqual(number(0.00000001), '0');
});
