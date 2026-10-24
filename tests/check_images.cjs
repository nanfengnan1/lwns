/* Chromium CDP + serve_image_fixture.py --large-library; Node 22+, isolated data/tags only. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const [debugURL, appURL, outputDirectory] = process.argv.slice(2);
(async () => {
  const assets = JSON.parse(fs.readFileSync(path.join(outputDirectory, 'fixture.json'), 'utf8'));
  assert.ok(assets.prefix.startsWith('rov-img-'));
  const target = await (await fetch(debugURL + '/json/new?about:blank', {method: 'PUT'})).json();
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise(r => ws.addEventListener('open', r, {once: true}));
  let id = 0;
  const pending = new Map(), errors = [], checks = [];
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const key = ++id, timer = setTimeout(() => { pending.delete(key); reject(Error('Timeout ' + method)); }, 20000);
    pending.set(key, {resolve, reject, timer}); ws.send(JSON.stringify({id: key, method, params}));
  });
  ws.addEventListener('message', event => {
    const msg = JSON.parse(event.data), item = pending.get(msg.id);
    if (item) { clearTimeout(item.timer); pending.delete(msg.id); msg.error ? item.reject(Error(JSON.stringify(msg.error))) : item.resolve(msg.result); }
    if (msg.method === 'Runtime.exceptionThrown') errors.push(msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text);
    if (msg.method === 'Page.javascriptDialogOpening') send('Page.handleJavaScriptDialog', {accept: true}).catch(() => {});
  });
  const evaluate = async expression => {
    const result = await send('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
    if (result.exceptionDetails) throw Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
    return result.result.value;
  };
  const wait = async (check, label) => { for (let i = 0; i < 600; i++) { if (await check()) return; await new Promise(r => setTimeout(r, 100)); } throw Error('Condition timed out: ' + (label || check)); };
  const waitDOM = expression => wait(() => evaluate(expression), expression);
  const click = async selector => {
    const point = await evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});if(!el)throw Error('Missing '+${JSON.stringify(selector)});el.scrollIntoView({block:'nearest'});const r=el.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
    await send('Input.dispatchMouseEvent', {type: 'mousePressed', ...point, button: 'left', clickCount: 1});
    await send('Input.dispatchMouseEvent', {type: 'mouseReleased', ...point, button: 'left', clickCount: 1});
  };
  const input = (selector, value) => evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});el.value=${JSON.stringify(value)};el.dispatchEvent(new Event(el.tagName==='SELECT'?'change':'input',{bubbles:true}));})()`);
  const file = async (selector, filename) => {
    const {root} = await send('DOM.getDocument');
    const {nodeId} = await send('DOM.querySelector', {nodeId: root.nodeId, selector});
    await send('DOM.setFileInputFiles', {nodeId, files: [path.join(outputDirectory, filename)]});
  };
  const screenshot = async name => { const shot = await send('Page.captureScreenshot'); fs.writeFileSync(path.join(outputDirectory, name), Buffer.from(shot.data, 'base64')); };
  const token = new URLSearchParams(new URL(appURL).hash.slice(1)).get('token');
  const api = endpoint => evaluate(`fetch(${JSON.stringify(endpoint)},{headers:{Authorization:${JSON.stringify('Bearer ' + token)}}}).then(r=>r.json())`);
  const job = async (action, mode) => {
    const old = new Set((await api('/api/images')).jobs.map(j => j.id));
    await action();
    let result;
    await wait(async () => { const data = await api('/api/images'); result = data.jobs.find(j => !old.has(j.id) && j.mode === mode); return result && ['success','error'].includes(result.state); }, mode + ' job');
    assert.equal(result.state, 'success', JSON.stringify(result));
    await waitDOM('document.querySelector("#start-image-job")?.closest("fieldset")?.disabled === false');
    checks.push(mode + ' job completed');
    return result;
  };
  const remove = async ref => {
    await input('#image-search', ref);
    await job(() => click(`.image-entry[data-image="${ref}"] .image-delete`), 'delete');
    assert.equal((await api('/api/images')).images.some(i => i.reference === ref), false);
  };
  await send('Page.enable'); await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', {width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false});
  try {
    await send('Page.navigate', {url: 'about:blank'});
    await send('Page.navigate', {url: appURL});
    await waitDOM('document.querySelectorAll("[data-device-group=router] .device-card").length === 60');
    const bootstrap = await api('/api/bootstrap');
    assert.equal(bootstrap.labs.length, 0, 'isolated fixture only');
    assert.ok(await evaluate('document.querySelector("#device-library").scrollHeight > document.querySelector("#device-library").clientHeight'));
    const before = await evaluate('document.querySelector("#manage-images").getBoundingClientRect().y');
    await click('.library-more');
    await waitDOM('document.querySelectorAll("[data-device-group=router] .device-card").length === 120');
    assert.equal(await evaluate('document.querySelector("#manage-images").getBoundingClientRect().y'), before);
    await input('#device-search', '测试路由器 199');
    await waitDOM('document.querySelectorAll(".device-card").length === 1');
    await input('#device-search', ''); await click('[data-category=router]');
    await waitDOM('document.querySelectorAll("[data-device-group=router] .device-card").length === 0');
    assert.equal(await evaluate('document.querySelectorAll("[data-device-group=host] .device-card").length'), bootstrap.catalog.filter(c => c.kind === 'host').length);
    assert.equal(await evaluate('document.querySelector("[data-category=all]")'), null);
    await click('[data-category=router]');
    await screenshot('device-library.png'); checks.push('200+ devices: pagination, search, categories, independent scroll, fixed footer');
    await click('#manage-images');
    await waitDOM('document.querySelector("#image-manager").open && !document.querySelector("#start-image-job").closest("fieldset").disabled');
    await click('[data-image-mode=archive]'); await file('#image-archive-file', 'image.tar.xz');
    await input('#image-title', '浏览器归档设备'); await input('#image-template', 'linux-host');
    await job(() => click('#start-image-job'), 'archive');
    await screenshot('image-imported.png');
    const ref = assets.prefix + ':archive';
    await input('#image-search', ref); await click(`.image-entry[data-image="${ref}"] .image-settings`);
    await input('#edit-image-title', '浏览器自定义设备'); await click('#save-image-settings');
    await waitDOM('!document.querySelector("#image-edit-form")');
    await click('#close-images'); await input('#device-search', '浏览器自定义设备');
    await waitDOM('document.querySelectorAll(".device-card").length === 1');
    const nodesBefore = await evaluate('document.querySelectorAll(".topology-node").length');
    await click('.device-card');
    await waitDOM(`document.querySelectorAll(".topology-node").length === ${nodesBefore + 1}`);
    checks.push('imported image settings update library and create canvas device');
    await click('#manage-images'); await remove(ref);
    await click('[data-image-mode=address]'); await input('#image-address', assets.url);
    await job(() => click('#start-image-job'), 'url');
    await remove(ref);
    await click('[data-image-mode=build]'); await input('#build-image-tag', assets.prefix + ':browser-build');
    const dockerfile = `FROM scratch\nLABEL io.route-ovs.image-test="${assets.prefix}"\nCMD ["/unused"]\n`;
    fs.writeFileSync(path.join(outputDirectory, 'Dockerfile'), dockerfile);
    await file('#dockerfile-file', 'Dockerfile');
    await waitDOM(`document.querySelector('#dockerfile-content').value === ${JSON.stringify(dockerfile)}`);
    await job(() => click('#start-image-job'), 'build');
    await input('#image-search', assets.prefix); await screenshot('image-built.png');
    await evaluate('window.__imageCheckBeforeReload = true');
    await send('Page.reload'); await waitDOM('!window.__imageCheckBeforeReload && !!document.querySelector("#manage-images")');
    await click('#manage-images');
    await waitDOM('!document.querySelector("#start-image-job").closest("fieldset").disabled');
    assert.ok((await api('/api/images')).images.some(i => i.reference === assets.prefix + ':browser-build' && i.present));
    await remove(assets.prefix + ':browser-build');
    checks.push('page reload retains registry; deleting removes image and registry record');
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(outputDirectory, 'results.json'), JSON.stringify({passed: true, checks, browserErrors: errors}, null, 2));
    console.log('PASS: ' + checks.join('; '));
  } catch (error) { await screenshot('failure.png').catch(() => {}); throw error; }
  finally { ws.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
