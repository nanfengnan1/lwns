const { openImageManager } = require('./browser_projects.cjs');
/* Node 22+, Chromium CDP, serve_library_fixture.py; no real Docker mutations. */
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const [debugURL, appURL, output] = process.argv.slice(2);
if (!debugURL || !appURL || !output) throw Error('Expected DEBUG_URL APP_URL OUTPUT_DIR');
(async () => {
  fs.mkdirSync(output, {recursive: true});
  const target = await (await fetch(debugURL + '/json/new?about:blank', {method: 'PUT'})).json();
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise(resolve => ws.addEventListener('open', resolve, {once: true}));
  let id = 0;
  const pending = new Map(), errors = [], requests = [];
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const key = ++id, timer = setTimeout(() => { pending.delete(key); reject(Error('Timeout ' + method)); }, 15000);
    pending.set(key, {resolve, reject, timer}); ws.send(JSON.stringify({id: key, method, params}));
  });
  ws.addEventListener('message', event => {
    const msg = JSON.parse(event.data), item = pending.get(msg.id);
    if (item) { clearTimeout(item.timer); pending.delete(msg.id); msg.error ? item.reject(Error(JSON.stringify(msg.error))) : item.resolve(msg.result); }
    if (msg.method === 'Runtime.exceptionThrown') errors.push(msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text);
    if (msg.method === 'Network.requestWillBeSent') requests.push(msg.params.request.url);
    if (msg.method === 'Page.javascriptDialogOpening') void send('Page.handleJavaScriptDialog', {accept: true});
  });
  const evaluate = async expression => {
    const r = await send('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
    if (r.exceptionDetails) throw Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    return r.result.value;
  };
  const wait = async expression => {
    for (let i = 0; i < 200; i++) { if (await evaluate(expression)) return; await new Promise(r => setTimeout(r, 100)); }
    throw Error('Condition not met: ' + expression + '; ' + await evaluate('document.querySelector("#toast")?.textContent'));
  };
  const click = async selector => {
    const point = await evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});if(!e)throw Error('Missing element');e.scrollIntoView({block:'nearest'});const r=e.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}})()`);
    for (const type of ['mousePressed', 'mouseReleased']) await send('Input.dispatchMouseEvent', {type, ...point, button: 'left', clickCount: 1});
  };
  const input = (selector, value) => evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});e.value=${JSON.stringify(value)};e.dispatchEvent(new Event(e.tagName==='SELECT'?'change':'input',{bubbles:true}));})()`);
  const shot = async name => { const r = await send('Page.captureScreenshot'); fs.writeFileSync(path.join(output, name), Buffer.from(r.data, 'base64')); };
  const token = new URLSearchParams(new URL(appURL).hash.slice(1)).get('token');
  const api = (endpoint, method = 'GET') => evaluate(`fetch(${JSON.stringify(endpoint)},{method:${JSON.stringify(method)},headers:{Authorization:${JSON.stringify('Bearer ' + token)}}}).then(r=>r.json())`);
  const ready = () => wait('!!document.querySelector("#start-image-job") && !document.querySelector("#start-image-job").closest("fieldset").disabled');
  const row = ref => '.image-entry[data-image="' + ref + '"]';
  try {
    await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable');
    await send('Emulation.setDeviceMetricsOverride', {width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false});
    await send('Page.navigate', {url: appURL});
    await wait('!!document.querySelector("#menu-tools")');
    assert.equal(requests.some(url=>/\/(DeviceTerminal|ImageManager|CaptureManager)-.*\.js/.test(url)),false);
    assert.equal(await evaluate('!!document.querySelector("#image-manager")'),false);
    await openImageManager(evaluate,wait,click); await ready();
    assert.equal(await evaluate('document.querySelector("#image-manager").open'),true,'first async mount opens the dialog');
    assert.ok(requests.some(url=>/\/ImageManager-.*\.js/.test(url)));
    await evaluate('window.retainedImageDialog=document.querySelector("#image-manager")');
    assert.equal((await api('/api/images')).images.some(item => item.reference === 'system/protected:latest'), false);
    await click('#refresh-images'); await ready();
    assert.equal((await api('/api/images')).images.some(item => item.reference === 'system/protected:latest'), false);
    await shot('managed-images.png');
    await click('[data-image-filter=missing]');
    assert.equal(await evaluate('document.querySelectorAll(".image-entry").length'), 0);
    assert.ok(await evaluate('!!document.querySelector(".image-empty")'));
    await click('[data-image-filter=present]');
    assert.ok(await evaluate('document.querySelectorAll(".image-entry").length > 200'));
    await click('[data-image-filter=all]');
    await input('#image-search', '测试路由器 199');
    assert.equal(await evaluate('document.querySelectorAll(".image-entry").length'), 1);
    await click('[data-image-mode=local]');
    await input('#local-image-reference', 'system/protected:latest');
    await input('#image-title', '已有镜像引用');
    await input('#image-template', 'linux-host');
    await click('#start-image-job'); await ready();
    await input('#image-search', 'system/protected:latest');
    await wait(`!!document.querySelector('${row('system/protected:latest')}')`);
    assert.equal(await evaluate(`document.querySelector('${row('system/protected:latest')} .image-delete').textContent.trim()`), '移出清单');
    assert.equal(await evaluate('document.querySelector("#toggle-image-log").getAttribute("aria-expanded")'), 'true');
    const adopted = (await api('/api/images')).images.find(item => item.reference === 'system/protected:latest');
    assert.equal(adopted.can_delete, false);
    const denied = await api('/api/images/' + adopted.id, 'DELETE');
    await wait(`fetch('/api/images',{headers:{Authorization:${JSON.stringify('Bearer ' + token)}}}).then(r=>r.json()).then(d=>d.jobs.find(j=>j.id===${JSON.stringify(denied.id)})?.state==='error')`);
    await ready();
    await click(row('system/protected:latest') + ' .image-delete'); await ready();
    await wait('document.querySelectorAll(".image-entry").length === 0');
    // Re-adoption proves forgetting kept the simulated host image.
    await click('#start-image-job'); await ready();
    await wait(`!!document.querySelector('${row('system/protected:latest')}')`);
    await click(row('system/protected:latest') + ' .image-delete'); await ready();
    await click('[data-image-mode=address]');
    await input('#image-address', 'fixture/managed:latest');
    await input('#image-title', '新建实验镜像');
    await input('#image-template', 'frr');
    await click('#start-image-job'); await ready();
    await input('#image-search', 'fixture/managed:latest');
    await wait(`!!document.querySelector('${row('fixture/managed:latest')}')`);
    assert.equal(await evaluate(`document.querySelector('${row('fixture/managed:latest')} .image-delete').textContent.trim()`), '删除镜像');
    assert.ok(await evaluate(`!!document.querySelector('${row('fixture/managed:latest')} .image-forget')`));
    await click(row('fixture/managed:latest') + ' .image-settings');
    assert.ok(await evaluate('!!document.querySelector(".image-entry.selected")'));
    await input('#edit-image-title', '实验镜像改名'); await click('#save-image-settings');
    await wait('!document.querySelector("#image-edit-form")');
    await click(row('fixture/managed:latest') + ' .image-delete'); await ready();
    await wait('document.querySelectorAll(".image-entry").length === 0');
    await input('#image-search', '');
    await click('#toggle-image-log');
    assert.equal(await evaluate('document.querySelector("#toggle-image-log").getAttribute("aria-expanded")'), 'false');
    await send('Emulation.setDeviceMetricsOverride', {width: 1000, height: 720, deviceScaleFactor: 1, mobile: false});
    await click('[data-image-mode=archive]');
    assert.ok(await evaluate('(()=>{const e=document.querySelector("#image-manager");return e.scrollWidth<=e.clientWidth+1})()'), 'no modal horizontal overflow');
    await shot('managed-images-compact.png');
    await click('#close-images'); await openImageManager(evaluate,wait,click); await ready();
    assert.equal(await evaluate('document.querySelector("#image-manager") === window.retainedImageDialog'),true,'dialog survives close/reopen');
    assert.equal(await evaluate('document.querySelector("[data-image-mode=archive]").classList.contains("active")'),true,'selected import mode is retained');
    assert.equal((await api('/api/images')).images.some(item => item.reference === 'system/protected:latest'), false);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ok: true, checks: ['host images hidden on refresh', 'state filters and search', 'explicit local reference', 'backend rejects protected deletion', 'forget preserves local image', 'owned image settings and deletion', 'collapsible task logs', '1000px layout without overflow'], screenshots: output}, null, 2));
  } catch (error) { await shot('failed.png'); throw error; }
  finally { ws.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
