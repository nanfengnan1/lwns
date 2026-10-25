/* Read-only browser handshake check; no valid terminal ticket is requested.
 * node tests/check_proxy_websocket.cjs DEBUG_URL APP_URL FOREIGN_PAGE_URL OUTPUT_DIR
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const [debugURL, appURL, foreignPageURL, output] = process.argv.slice(2);
if (!debugURL || !appURL || !foreignPageURL || !output)
  throw Error('Expected DEBUG_URL APP_URL FOREIGN_PAGE_URL OUTPUT_DIR');

(async () => {
  const app = new URL(appURL), foreign = new URL(foreignPageURL);
  assert.notEqual(app.origin, foreign.origin, 'Use different browser origins');
  const terminalURL = new URL('/api/terminal', app);
  terminalURL.protocol = app.protocol === 'https:' ? 'wss:' : 'ws:';
  const target = await (await fetch(debugURL + '/json/new?about:blank', { method: 'PUT' })).json();
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true });
    socket.addEventListener('error', reject, { once: true });
  });
  let sequence = 0;
  const pending = new Map(), handshakes = new Map();
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence, timer = setTimeout(() => {
      pending.delete(id);
      reject(Error('CDP timeout: ' + method));
    }, 20000);
    pending.set(id, { resolve, reject, timer });
    socket.send(JSON.stringify({ id, method, params }));
  });
  socket.addEventListener('message', ({ data }) => {
    const message = JSON.parse(data), job = pending.get(message.id);
    if (job) {
      clearTimeout(job.timer);
      pending.delete(message.id);
      message.error ? job.reject(Error(JSON.stringify(message.error))) : job.resolve(message.result);
    }
    const params = message.params;
    if (message.method === 'Network.webSocketCreated' && params.url === terminalURL.href)
      handshakes.set(params.requestId, { url: params.url, origin: null, status: null, errors: [] });
    const handshake = handshakes.get(params?.requestId);
    if (handshake && message.method === 'Network.webSocketWillSendHandshakeRequest')
      handshake.origin = params.request.headers.Origin || params.request.headers.origin;
    if (handshake && message.method === 'Network.webSocketHandshakeResponseReceived')
      handshake.status = params.response.status;
    if (handshake && message.method === 'Network.webSocketFrameError')
      handshake.errors.push(params.errorMessage);
  });
  const evaluate = async expression => {
    const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails)
      throw Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
    return result.result.value;
  };
  const navigate = async url => {
    await send('Page.navigate', { url });
    const origin = new URL(url).origin;
    for (let attempt = 0; attempt < 100; attempt++) {
      if (await evaluate(`location.origin === ${JSON.stringify(origin)} && document.readyState === 'complete'`)) return;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    throw Error('Navigation not complete: ' + origin);
  };
  const probe = () => evaluate(`new Promise(resolve => {
    const result = {opened:false, messages:[], error:false, code:null, timedOut:false};
    const ws = new WebSocket(${JSON.stringify(terminalURL.href)});
    let complete = false;
    const finish = () => {if (complete) return; complete=true; clearTimeout(timer); resolve(result);};
    const timer = setTimeout(() => {result.timedOut=true;ws.close();finish();},8000);
    ws.onopen = () => {result.opened=true;ws.send(JSON.stringify({type:'connect',ticket:'invalid-proxy-browser-check',cols:80,rows:24}));};
    ws.onmessage = event => {try {result.messages.push(JSON.parse(event.data));} catch {result.messages.push(String(event.data));}};
    ws.onerror = () => {result.error=true;};
    ws.onclose = event => {result.code=event.code;finish();};
  })`);
  let sameOrigin, foreignOrigin, success = false;
  try {
    await send('Page.enable');
    await send('Runtime.enable');
    await send('Network.enable');
    await navigate(appURL);
    sameOrigin = await probe();
    assert.equal(sameOrigin.timedOut, false);
    assert.equal(sameOrigin.opened, true, 'Same-origin WebSocket handshake must succeed through Vite');
    assert.ok(sameOrigin.messages.some(message => message.type === 'error' && /凭证.*(无效|过期|使用)/.test(message.message)),
      'An invalid ticket is rejected by the terminal application after handshake');
    const accepted = [...handshakes.values()].at(-1);
    assert.equal(accepted.origin, app.origin);
    assert.equal(accepted.status, 101);

    await navigate(foreignPageURL);
    foreignOrigin = await probe();
    assert.equal(foreignOrigin.timedOut, false);
    assert.equal(foreignOrigin.opened, false, 'Foreign-origin WebSocket must fail before opening a terminal');
    assert.equal(foreignOrigin.error, true);
    assert.deepEqual(foreignOrigin.messages, []);
    const rejected = [...handshakes.values()].at(-1);
    assert.equal(rejected.origin, foreign.origin);
    assert.ok(rejected.status === 403 || rejected.errors.some(error => error.includes('403')),
      'Foreign-origin handshake must be rejected with HTTP 403, not a network failure');
    success = true;
  } finally {
    await send('Page.close').catch(() => {});
    socket.close();
    for (const job of pending.values()) clearTimeout(job.timer);
    fs.mkdirSync(output, { recursive: true });
    fs.writeFileSync(path.join(output, 'websocket-origin-results.json'), JSON.stringify({
      ok: success, appOrigin: app.origin, foreignOrigin: foreign.origin,
      sameOriginResult: sameOrigin, foreignOriginResult: foreignOrigin,
      handshakes: [...handshakes.values()],
    }, null, 2));
  }
  console.log(JSON.stringify({ ok: success, checks: [
    'same-origin Vite WebSocket upgrades with HTTP 101',
    'invalid ticket produces an application error without creating a terminal',
    'foreign-origin WebSocket is rejected with HTTP 403',
  ], output }, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; });
