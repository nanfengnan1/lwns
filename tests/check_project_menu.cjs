/* Isolated preview-backend acceptance for the experiment menu.
 * node tests/check_project_menu.cjs DEBUG_URL APP_URL_WITH_TOKEN OUTPUT_DIR
 * Opens its own CDP tab and creates/deletes only a uniquely named test lab.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const [debugURL, appURL, output] = process.argv.slice(2);
if (!debugURL || !appURL || !output) throw Error('Expected DEBUG_URL APP_URL_WITH_TOKEN OUTPUT_DIR');

(async () => {
  const app = new URL(appURL), token = new URLSearchParams(app.hash.slice(1)).get('token');
  assert.ok(token, 'Use an isolated preview backend with a test token');
  const id = 'menu-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 6);
  const name = '菜单验收 ' + id;
  const example = JSON.parse(fs.readFileSync(path.join(__dirname, '../examples/basic-lab.json'), 'utf8'));
  const topology = { ...example, id, name };
  fs.mkdirSync(output, { recursive: true });
  const target = await (await fetch(debugURL + '/json/new?about:blank', { method: 'PUT' })).json();
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise(resolve => socket.addEventListener('open', resolve, { once: true }));
  let seq = 0, acceptDialog = true, dialogCount = 0;
  const jobs = new Map(), errors = [];
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++seq, timer = setTimeout(() => { jobs.delete(id); reject(Error('Timeout: ' + method)); }, 15000);
    jobs.set(id, { resolve, reject, timer });
    socket.send(JSON.stringify({ id, method, params }));
  });
  socket.addEventListener('message', ({ data }) => {
    const message = JSON.parse(data), job = jobs.get(message.id);
    if (job) {
      clearTimeout(job.timer); jobs.delete(message.id);
      message.error ? job.reject(Error(JSON.stringify(message.error))) : job.resolve(message.result);
    }
    if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text);
    if (message.method === 'Page.javascriptDialogOpening') {
      dialogCount++;
      const accept = acceptDialog; acceptDialog = true;
      void send('Page.handleJavaScriptDialog', { accept });
    }
  });
  const evaluate = async expression => {
    const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true, userGesture: true });
    if (result.exceptionDetails) throw Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
    return result.result.value;
  };
  const wait = async expression => {
    for (let i = 0; i < 100; i++) {
      if (await evaluate(expression)) return;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    throw Error('Condition not met: ' + expression + '; state=' + JSON.stringify(await evaluate('({toast:document.querySelector("#toast")?.textContent,focus:document.activeElement.outerHTML.slice(0,200),popup:document.querySelector(".menu-popover")?.id,environment:document.querySelector("#environment")?.textContent})')));
  };
  const point = selector => evaluate(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el) throw Error('Missing: '+${JSON.stringify(selector)}); el.scrollIntoView({block:'nearest'}); const r = el.getBoundingClientRect(); return { x:r.x+r.width/2, y:r.y+r.height/2 }; })()`);
  const click = async selector => { const location = await point(selector); for (const type of ['mousePressed', 'mouseReleased']) await send('Input.dispatchMouseEvent', { type, ...location, button:'left', clickCount:1 }); };
  const key = async (value, code = value, virtual = 0) => {
    await send('Input.dispatchKeyEvent', { type:'keyDown', key:value, code, windowsVirtualKeyCode:virtual });
    await send('Input.dispatchKeyEvent', { type:'keyUp', key:value, code, windowsVirtualKeyCode:virtual });
  };
  const input = (selector, value) => evaluate(`(() => { const el=document.querySelector(${JSON.stringify(selector)}); el.value=${JSON.stringify(value)}; el.dispatchEvent(new Event('input',{bubbles:true})); })()`);
  const action = async (menu, item) => {
    if (!await evaluate(`!!document.querySelector('#popup-${menu}')`)) await click('#menu-' + menu);
    await wait(`!!document.querySelector(${JSON.stringify(item)})`);
    await click(item);
  };
  const snapshot = async filename => { const shot = await send('Page.captureScreenshot'); fs.writeFileSync(path.join(output, filename), Buffer.from(shot.data, 'base64')); };
  const importDraft = async value => {
    await evaluate(`(() => { const input=document.querySelector('#import-file'), files=new DataTransfer(); files.items.add(new File([${JSON.stringify(JSON.stringify(value))}], 'test-topology.json', {type:'application/json'})); input.files=files.files; input.dispatchEvent(new Event('change',{bubbles:true})); })()`);
    await wait(`document.querySelector('#lab-name').textContent.includes(${JSON.stringify(value.name)})`);
  };
  const server = async (suffix, method = 'GET') => fetch(app.origin + suffix, { method, headers:{ Authorization:'Bearer ' + token } });
  try {
    await send('Page.enable'); await send('Runtime.enable');
    await send('Emulation.setDeviceMetricsOverride', { width:1440, height:960, deviceScaleFactor:1, mobile:false });
    await send('Page.navigate', { url:appURL });
    await wait('!!document.querySelector("#menu-experiment") && !document.querySelector("#access-dialog")?.open && document.querySelector("#empty-state")');
    await wait('document.querySelector("#environment")?.textContent.includes("设计模式")');

    // Keyboard menus: arrows change groups and items; Escape and Tab restore a useful focus.
    await evaluate('document.querySelector("#menu-experiment").focus()');
    await key('ArrowDown', 'ArrowDown', 40);
    await wait('document.activeElement.id === "new-lab"');
    await key('ArrowDown', 'ArrowDown', 40);
    assert.equal(await evaluate('document.activeElement.id'), 'open-lab');
    await key('ArrowRight', 'ArrowRight', 39);
    await wait('document.activeElement.id === "menu-library"');
    await key('Escape', 'Escape', 27);
    await wait('!document.querySelector(".menu-popover")');
    assert.equal(await evaluate('document.activeElement.id'), 'menu-view');
    await key('ArrowDown', 'ArrowDown', 40);
    await wait('!!document.querySelector("#popup-view")');
    await key('Tab', 'Tab', 9);
    await wait('!document.querySelector(".menu-popover")');
    assert.equal(await evaluate('!!document.activeElement.closest(".workbench-menu")'), false);
    await click('#menu-experiment');
    await click('#counts');
    await wait('!document.querySelector(".menu-popover")');

    // Simulate an empty response in this tab only; never delete other test labs.
    await evaluate(`window.menuRealFetch=window.fetch; window.fetch=(url,init)=>String(url)==='/api/labs' ? Promise.resolve(new Response('[]',{status:200})) : window.menuRealFetch(url,init)`);
    await action('experiment', '#open-lab');
    await wait('document.querySelector("#open-lab-dialog").open && document.querySelector(".open-lab-empty")?.textContent.includes("还没有保存")');
    assert.equal(await evaluate('document.querySelector("#confirm-open-lab").disabled'), true);
    await snapshot('open-empty.png');
    await key('Escape', 'Escape', 27);
    await wait('!document.querySelector("#open-lab-dialog").open');
    await evaluate('window.fetch=window.menuRealFetch');

    // Create a unique draft, then verify menu keys never mutate selected canvas devices.
    await importDraft(topology);
    await wait('document.querySelectorAll(".topology-node").length===5');
    await click('.topology-node[data-node="r1"] .node-name');
    await click('#menu-experiment');
    await key('ArrowDown', 'ArrowDown', 40);
    await wait('document.activeElement.id === "new-lab"');
    // Hover a different group while focus is in the old menu (the old DOM is destroyed).
    await send('Input.dispatchMouseEvent', { type:'mouseMoved', ...await point('#menu-view') });
    await wait('!!document.querySelector("#popup-view")');
    assert.equal(await evaluate('document.activeElement.id'), 'menu-library');
    for (const value of ['Delete', 'v', 'c', 't']) await key(value, value === 'Delete' ? 'Delete' : 'Key' + value.toUpperCase(), value === 'Delete' ? 46 : value.toUpperCase().charCodeAt(0));
    assert.equal(await evaluate('document.querySelectorAll(".topology-node").length'), 5);
    assert.equal(await evaluate('document.querySelector("#select-tool").classList.contains("active")'), true);
    assert.equal(await evaluate('document.querySelector("#add-annotation").getAttribute("aria-pressed")'), 'false');
    // Explicitly blur the menu to reproduce body-focus shortcuts while a menu is open.
    await evaluate('document.activeElement.blur()');
    for (const value of ['Delete', 'c', 't']) await key(value, value === 'Delete' ? 'Delete' : 'Key' + value.toUpperCase(), value === 'Delete' ? 46 : value.toUpperCase().charCodeAt(0));
    assert.equal(await evaluate('document.querySelectorAll(".topology-node").length'), 5);
    assert.equal(await evaluate('document.querySelector("#select-tool").classList.contains("active")'), true);
    await click('#counts');
    await action('experiment', '#menu-save');
    await wait('document.querySelector("#save-state").textContent === "已保存"');
    assert.equal((await (await server('/api/labs/' + id)).json()).topology.name, name);

    // Sidebar visibility and menu checkmarks remain in sync, without dirtying the project.
    const leftCollapsed = await evaluate('document.querySelector(".sidebar-panel.left").classList.contains("is-collapsed")');
    await click('#menu-view');
    assert.equal(await evaluate('document.querySelector("#menu-library").getAttribute("aria-checked")'), String(!leftCollapsed));
    await click('#menu-library');
    assert.equal(await evaluate('document.querySelector(".sidebar-panel.left").classList.contains("is-collapsed")'), !leftCollapsed);
    await click('#menu-view');
    assert.equal(await evaluate('document.querySelector("#menu-library").getAttribute("aria-checked")'), String(leftCollapsed));
    await click('#menu-library');
    assert.equal(await evaluate('document.querySelector("#save-state").textContent'), '已保存');

    // Search cannot accidentally open a hidden selection. Declining discard keeps the draft.
    const draft = { ...topology, id: id + '-d', name: '未保存的菜单草稿' };
    await importDraft(draft);
    await action('experiment', '#open-lab');
    await wait('document.querySelector("#open-lab-dialog").open && document.querySelector(".open-lab-list").getAttribute("aria-busy") === "false"');
    await input('#open-lab-search', id);
    await wait('document.querySelectorAll(".open-lab-item").length === 1');
    await click(`.open-lab-item[data-lab-id="${id}"]`);
    await input('#open-lab-search', 'no-match-' + id);
    await wait('!document.querySelector(".open-lab-item")');
    assert.equal(await evaluate('document.querySelector("#confirm-open-lab").disabled'), true);
    await input('#open-lab-search', id);
    await wait('document.querySelectorAll(".open-lab-item").length === 1');
    const beforeDialogs = dialogCount;
    acceptDialog = false;
    await click('#confirm-open-lab');
    await wait('document.querySelector("#open-lab-dialog").open');
    assert.equal(dialogCount, beforeDialogs + 1);
    assert.ok(await evaluate('document.querySelector("#lab-name").textContent.includes("未保存的菜单草稿")'));
    await snapshot('open-saved.png');
    await click('#confirm-open-lab');
    await wait(`!document.querySelector('#open-lab-dialog').open && document.querySelector('#lab-name').textContent.includes(${JSON.stringify(name)})`);
    assert.equal(await evaluate('document.querySelector("#save-state").textContent'), '已保存');

    // Refresh starts blank, and saved work remains available only through explicit open.
    await send('Page.reload');
    await wait('!!document.querySelector("#empty-state") && !document.querySelector("#empty-state").hidden && document.querySelector("#environment")?.textContent.includes("设计模式") && !document.querySelector("#access-dialog")?.open');
    await action('experiment', '#open-lab');
    await wait(`!!document.querySelector('.open-lab-item[data-lab-id="${id}"]')`);
    await click(`.open-lab-item[data-lab-id="${id}"]`);
    await click('#confirm-open-lab');
    await wait('document.querySelectorAll(".topology-node").length === 5');

    // An expired token during listing must open login without discarding unsaved work.
    await importDraft(draft);
    await evaluate(`window.menuRealFetch=window.fetch; window.fetch=(url,init)=>String(url)==='/api/labs' ? Promise.resolve(new Response(JSON.stringify({error:'Unauthorized'}),{status:401})) : window.menuRealFetch(url,init)`);
    await action('experiment', '#open-lab');
    await wait('document.querySelector("#access-dialog").open && !document.querySelector("#open-lab-dialog").open');
    assert.ok(await evaluate('document.querySelector("#lab-name").textContent.includes("未保存的菜单草稿")'));
    await evaluate('window.fetch=window.menuRealFetch');
    await input('#access-token', token);
    await click('#access-form button[type="submit"]');
    await wait('!document.querySelector("#access-dialog").open');
    assert.ok(await evaluate('document.querySelector("#lab-name").textContent.includes("未保存的菜单草稿")'));
    assert.equal(await evaluate('document.querySelectorAll(".topology-node").length'), 5);
    assert.deepEqual(errors, []);
    console.log('PASS: menu keyboard/focus, hover and body shortcut isolation, outside click, empty/search/open/discard, menu save, sidebar checks, explicit startup open, expired-token recovery.');
  } finally {
    try {
      const result = await server('/api/labs/' + id);
      if (result.ok) {
        const record = await result.json();
        assert.equal(record.topology.name, name, 'Delete only the unique experiment owned by this run');
        const removed = await server('/api/labs/' + id, 'DELETE');
        assert.ok(removed.ok, 'Failed to clean the test experiment');
      } else if (result.status === 400) assert.equal((await result.json()).error, '实验不存在');
      else assert.equal(result.status, 404);
    } finally {
      await evaluate('window.onbeforeunload=null; window.addEventListener("beforeunload", e=>e.stopImmediatePropagation(), {capture:true})').catch(() => {});
      await send('Page.close').catch(() => {});
      socket.close();
    }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
