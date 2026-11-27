/**
 * unit-test-15 (REV-13, REV-15): the create as the web UI runs it, against a fake HttpClient.
 *
 * Runs with Node's test runner (`make frontend-test`), no browser: the service is built
 * by hand, and the RxJS TestScheduler makes the 1.5 s polls and the 10-minute limit
 * virtual, so every case runs in milliseconds.
 */
// Angular's libraries are partially compiled: outside the CLI they need the JIT compiler.
import '@angular/compiler';
import { strict as assert } from 'node:assert';
import { afterEach, beforeEach, describe, it } from 'node:test';
import { HttpClient, HttpErrorResponse, HttpHeaders } from '@angular/common/http';
import { Observable, defer, of, throwError } from 'rxjs';
import { TestScheduler } from 'rxjs/testing';
import { NetworkCreateRequest, NetworkStatus } from '../models/network.models';
import { AuthService } from './auth.service';
import { ApiError, reservationGoneText } from './recovery-response';
import { WilabApiService } from './wilab-api.service';

type Answer = () => Observable<unknown>;

// A browser global that handleError checks; Node has none.
if (!('ErrorEvent' in globalThis)) {
  (globalThis as Record<string, unknown>)['ErrorEvent'] = class ErrorEvent extends Event {};
}

class FakeHttp {
  posts: Answer[] = [];
  gets: Answer[] = [];
  getCalls: number[] = [];   // virtual time of each GET
  postCalls = 0;
  constructor(private readonly scheduler: TestScheduler) {}

  // Cold, like HttpClient: each subscription (a retry too) sends the request again.
  post(): Observable<unknown> {
    return defer(() => {
      this.postCalls += 1;
      const next = this.posts.shift();
      assert.ok(next, 'unexpected POST');
      return next();
    });
  }

  get(): Observable<unknown> {
    return defer(() => {
      this.getCalls.push(this.scheduler.now());
      const next = this.gets.shift();
      assert.ok(next, `unexpected GET at ${this.scheduler.now()} ms`);
      return next();
    });
  }
}

function status(fields: Partial<NetworkStatus>): NetworkStatus {
  return { interface: 'wlan0', active: false, runtime_state: null, ...fields } as NetworkStatus;
}

const starting = status({ runtime_state: 'starting' });
const running = status({ active: true });

function httpError(code: number, detail: object | null = null, headers: Record<string, string> = {}): Answer {
  return () => throwError(() => new HttpErrorResponse({
    status: code, error: detail === null ? null : { detail }, headers: new HttpHeaders(headers),
  }));
}

const ok = (body: NetworkStatus): Answer => () => of(body);

interface Outcome {
  values: NetworkStatus[];
  error: ApiError | Error | null;
  completed: boolean;
  endedAt: number | null;
}

const REQUEST = { wifi: { ssid: 'spec' } } as unknown as NetworkCreateRequest;

describe('WilabApiService.startNetwork', () => {
  let scheduler: TestScheduler;
  let http: FakeHttp;
  let api: WilabApiService;
  const quiet = console.error;

  beforeEach(() => {
    scheduler = new TestScheduler((actual, expected) => assert.deepEqual(actual, expected));
    http = new FakeHttp(scheduler);
    const auth = { getToken: () => 'token' } as unknown as AuthService;
    api = new WilabApiService(http as unknown as HttpClient, auth);
    console.error = () => undefined;   // handleError logs every failure
  });

  afterEach(() => {
    console.error = quiet;
  });

  function run(until?: number): Outcome {
    const outcome: Outcome = { values: [], error: null, completed: false, endedAt: null };
    scheduler.run(({ flush }) => {
      const subscription = api.startNetwork('r1', REQUEST).subscribe({
        next: value => outcome.values.push(value),
        error: error => { outcome.error = error; outcome.endedAt = scheduler.now(); },
        complete: () => { outcome.completed = true; outcome.endedAt = scheduler.now(); },
      });
      if (until !== undefined) {
        scheduler.schedule(() => subscription.unsubscribe(), until);
      }
      flush();
    });
    return outcome;
  }

  it('202 then polling ends with the running network', () => {
    http.posts.push(ok(starting));
    http.gets.push(ok(starting), ok(starting), ok(running));
    const outcome = run();
    assert.deepEqual(outcome.values.map(v => v.active), [false, true]);
    assert.equal(outcome.completed, true);
    assert.deepEqual(http.getCalls, [1500, 3000, 4500]);
  });

  it('200 on a running network ends at once, without polling', () => {
    http.posts.push(ok(running));
    const outcome = run();
    assert.deepEqual(outcome.values, [running]);
    assert.equal(outcome.completed, true);
    assert.equal(http.getCalls.length, 0);
  });

  it('202 then start_failed ends with the error to show', () => {
    const failed = status({
      runtime_state: 'start_failed',
      error: { code: 1013, reason: 'startup_failed', message: 'Failed to configure DHCP', stage: 'dhcp' },
    } as Partial<NetworkStatus>);
    http.posts.push(ok(starting));
    http.gets.push(ok(starting), ok(failed));
    const outcome = run();
    assert.equal(outcome.values.at(-1)?.runtime_state, 'start_failed');
    assert.equal(outcome.values.at(-1)?.error?.stage, 'dhcp');
    assert.equal(outcome.completed, true);
  });

  for (const reason of ['reservation_released', 'reservation_expired', 'reservation_invalidated', 'reservation_not_found']) {
    it(`404 ${reason} during the polling ends with a sentence, never the raw JSON`, () => {
      http.posts.push(ok(starting));
      http.gets.push(ok(starting), httpError(404, { code: 404, reason, message: 'Reservation gone' }));
      const outcome = run();
      assert.ok(outcome.error, 'the 404 must end the create');
      const text = reservationGoneText(outcome.error as ApiError);
      assert.ok(text && !text.includes('{'), `no sentence for ${reason}: ${text}`);
      assert.equal(http.getCalls.length, 2);   // no poll after the 404
    });
  }

  it('a poll without an answer or with a 5xx does not end the start', () => {
    http.posts.push(ok(starting));
    http.gets.push(
      httpError(0), httpError(502),
      httpError(503, { code: 1006, reason: 'device_busy', message: 'busy' }, { 'Retry-After': '2' }),
      ok(running),
    );
    const outcome = run();
    assert.equal(outcome.error, null);
    assert.equal(outcome.values.at(-1)?.active, true);
    assert.deepEqual(http.getCalls, [1500, 3000, 4500, 6000]);
  });

  it('a 401 during the polling ends the create with the error', () => {
    http.posts.push(ok(starting));
    http.gets.push(httpError(401, { code: 401, reason: 'unauthorized', message: 'Invalid token' }));
    const outcome = run();
    assert.ok(outcome.error);
    assert.equal((outcome.error as ApiError).originalError?.status, 401);
  });

  it('a cancelled start ends with the inactive network, not with success', () => {
    // The client stopped or released meanwhile: the server rolled back.
    const cancelled = status({ active: false, runtime_state: null });
    http.posts.push(ok(starting));
    http.gets.push(ok(starting), ok(cancelled));
    const outcome = run();
    const last = outcome.values.at(-1);
    assert.equal(outcome.completed, true);
    assert.equal(last?.active, false);
    assert.equal(last?.runtime_state, null);
  });

  it('unsubscribing stops the polling', () => {
    http.posts.push(ok(starting));
    http.gets.push(ok(starting), ok(starting), ok(starting), ok(starting));
    const outcome = run(3500);
    assert.deepEqual(http.getCalls, [1500, 3000]);
    assert.equal(outcome.completed, false);
  });

  it('a start that never ends gives up after 10 minutes', () => {
    http.posts.push(ok(starting));
    for (let i = 0; i < 500; i += 1) http.gets.push(ok(starting));
    const outcome = run();
    assert.ok(outcome.error);
    assert.equal(outcome.endedAt, 10 * 60 * 1000);
  });

  it('the create answered 503 / 1006 is repeated after Retry-After', () => {
    http.posts.push(
      httpError(503, { code: 1006, reason: 'device_busy', message: 'busy' }, { 'Retry-After': '2' }),
      ok(running),
    );
    const outcome = run();
    assert.equal(http.postCalls, 2);
    assert.deepEqual(outcome.values, [running]);
  });
});
