const { openSavedLab } = require('./browser_projects.cjs');
/* Real Chromium + serve_config_fixture.py. Node 22+; isolated test lab only. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const [debugURL, appURL, outputDirectory] = process.argv.slice(2);
(async () => {
  fs.mkdirSync(outputDirectory, {recursive: true});
  const targets = await (await fetch(debugURL + '/json')).json();
  const ws = new WebSocket(targets.find(t => t.type === 'page').webSocketDebuggerUrl);
  await new Promise(r => ws.addEventListener('open', r, {once: true}));
  let id = 0;
  const pending = new Map(), errors = [], channels = new Map();
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const key = ++id, timer = setTimeout(() => { pending.delete(key); reject(Error('Timeout ' + method)); }, 20000);
    pending.set(key, {resolve, reject, timer}); ws.send(JSON.stringify({id: key, method, params}));
  });
  ws.addEventListener('message', event => {
    const msg = JSON.parse(event.data), item = pending.get(msg.id);
    if (item) { clearTimeout(item.timer); pending.delete(msg.id); msg.error ? item.reject(Error(JSON.stringify(msg.error))) : item.resolve(msg.result); }
    if (msg.method === 'Runtime.exceptionThrown') errors.push(msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text);
    if (msg.method === 'Page.javascriptDialogOpening') send('Page.handleJavaScriptDialog', {accept: true}).catch(() => {});
    if (msg.method === 'Network.webSocketCreated') channels.set(msg.params.requestId, {output: '', closed: false});
    const channel = channels.get(msg.params?.requestId);
    if (channel && msg.method === 'Network.webSocketFrameReceived' && msg.params.response.opcode === 2)
      channel.output += Buffer.from(msg.params.response.payloadData, 'base64').toString();
    if (channel && msg.method === 'Network.webSocketClosed') channel.closed = true;
  });
  const evaluate = async expression => {
    const result = await send('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
    if (result.exceptionDetails) throw Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
    return result.result.value;
  };
  const wait = async check => { for (let i = 0; i < 300; i++) { if (await check()) return; await new Promise(r => setTimeout(r, 100)); } throw Error('Condition timed out: ' + check); };
  const waitDOM = expression => wait(() => evaluate(expression));
  const click = async (selector, count = 1) => {
    const point = await evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});el.scrollIntoView({block:'nearest'});const r=el.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
    for (let n = 1; n <= count; n++) {
      await send('Input.dispatchMouseEvent', {type: 'mousePressed', ...point, button: 'left', clickCount: n});
      await send('Input.dispatchMouseEvent', {type: 'mouseReleased', ...point, button: 'left', clickCount: n});
    }
  };
  const command = async text => {
    await send('Input.insertText', {text});
    await send('Input.dispatchKeyEvent', {type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, text: '\r'});
    await send('Input.dispatchKeyEvent', {type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13});
  };
  const screenshot = async name => { const shot = await send('Page.captureScreenshot'); fs.writeFileSync(path.join(outputDirectory, name), Buffer.from(shot.data, 'base64')); };
  const token = new URLSearchParams(new URL(appURL).hash.slice(1)).get('token');
  const api = endpoint => evaluate(`fetch(${JSON.stringify(endpoint)},{headers:{Authorization:${JSON.stringify('Bearer ' + token)}}}).then(r=>r.json())`);
  await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable');
  await send('Emulation.setDeviceMetricsOverride', {width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false});
  try {
    await send('Page.navigate', {url: appURL});
    await openSavedLab(evaluate, waitDOM, click);
    await waitDOM('document.querySelectorAll(".topology-node").length === 2');
    const bootstrap = await api('/api/bootstrap');
    const labId = bootstrap.labs[0].id;
    assert.ok(labId.startsWith('config-test-'), 'must use isolated fixture');
    await click('#fit');
    await click('.topology-node[data-node=r1] .node-body', 2);
    await waitDOM('document.querySelector(".terminal-state")?.textContent === "已连接"');
    const first = [...channels.values()].at(-1);
    await wait(() => first.output.includes('R1#'));
    await command('configure terminal'); await command('interface lo');
    await command('ip address 198.51.100.88/32'); await command('description WEB_SAVED');
    await command('exit'); await command('router ospf'); await command('ospf router-id 203.0.113.88'); await command('end');
    await command('show running-config');
    await wait(() => first.output.includes('ospf router-id 203.0.113.88'));
    await click('#save-device-config');
    await waitDOM('document.querySelector("#config-save-state")?.textContent.includes("Web 保存")');
    const config = (await api(`/api/labs/${labId}/configs/r1`)).r1;
    assert.ok(config.content.includes('WEB_SAVED'));
    assert.ok(config.content.includes('203.0.113.88'));
    assert.equal(first.closed, false, 'saving must keep the terminal session');
    await click('.config-panel summary');
    assert.equal(await evaluate('document.querySelector("#saved-device-config").value.includes("WEB_SAVED")'), true);
    await screenshot('config-saved.png');
    await click('#destroy');
    await waitDOM('document.querySelector("#deploy")?.disabled === false');
    assert.equal((await api(`/api/labs/${labId}/configs/r1`)).r1.content, config.content);
    assert.equal(await evaluate('document.querySelectorAll(".terminal-tab").length'), 0);
    await click('#deploy');
    await waitDOM('document.querySelector("#save-all-configs")?.disabled === false');
    assert.equal((await api(`/api/labs/${labId}`)).runtime.phase, 'running');
    await click('.topology-node[data-node=r1] .node-body', 2);
    await waitDOM('document.querySelector(".terminal-state")?.textContent === "已连接"');
    const restored = [...channels.values()].at(-1);
    await command('show running-config');
    await wait(() => restored.output.includes('WEB_SAVED') && restored.output.includes('203.0.113.88'));
    await command('show ip route');
    await wait(() => restored.output.includes('198.51.100.88/32'));
    await click('#save-all-configs');
    await waitDOM('document.querySelector("#save-all-configs")?.disabled === false');
    assert.equal(restored.closed, false);
    await screenshot('config-restored.png');
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(outputDirectory, 'results.json'), JSON.stringify({passed: true, checks: ['real terminal configuration', 'single-device Web save', 'disk preview', 'terminal remains connected', 'cleanup retains configuration', 'new containers restore OSPF and loopback', 'save all devices'], browserErrors: errors}, null, 2));
    console.log('PASS: terminal → Web save → cleanup → redeploy → restored OSPF and loopback');
  } catch (error) { await screenshot('failure.png').catch(() => {}); throw error; }
  finally { ws.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
