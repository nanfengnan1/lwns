/* Browser integration: isolated --preview backend, Chromium CDP and Node 22+.
 * node tests/check_sidebar_projects.cjs DEBUG_URL APP_URL_WITH_TOKEN OUTPUT_DIR
 * Creates and deletes one named test project; does not deploy containers.
 */
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const [debugURL, appURL, output] = process.argv.slice(2);
if (!debugURL || !appURL || !output) throw Error('Expected DEBUG_URL APP_URL OUTPUT_DIR');
(async () => {
  fs.mkdirSync(output, {recursive: true});
  const target = await (await fetch(debugURL + '/json/new?about:blank', {method:'PUT'})).json();
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise(resolve => ws.addEventListener('open', resolve, {once:true}));
  let seq = 0, savedId;
  const pending = new Map(), errors = [];
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++seq, timer = setTimeout(() => { pending.delete(id); reject(Error('Timeout: ' + method)); }, 15000);
    pending.set(id, {resolve, reject, timer}); ws.send(JSON.stringify({id, method, params}));
  });
  ws.addEventListener('message', event => {
    const m = JSON.parse(event.data), p = pending.get(m.id);
    if (p) { clearTimeout(p.timer); pending.delete(m.id); m.error ? p.reject(Error(JSON.stringify(m.error))) : p.resolve(m.result); }
    if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
    if (m.method === 'Page.javascriptDialogOpening') void send('Page.handleJavaScriptDialog', {accept:true});
  });
  const evaluate = async expression => {
    const r = await send('Runtime.evaluate', {expression, returnByValue:true, awaitPromise:true});
    if (r.exceptionDetails) throw Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    return r.result.value;
  };
  const wait = async expression => {
    for (let i=0; i<100; i++) { if (await evaluate(expression)) return; await new Promise(r => setTimeout(r, 100)); }
    throw Error('Condition not met: ' + expression + '; toast=' + await evaluate('document.querySelector("#toast")?.textContent'));
  };
  const point = selector => evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});e.scrollIntoView({block:'nearest'});const r=e.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}})()`);
  const click = async selector => { const p=await point(selector); for (const type of ['mousePressed','mouseReleased']) await send('Input.dispatchMouseEvent',{type,...p,button:'left',clickCount:1}); };
  const input = (selector, value) => evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('input',{bubbles:true}))})()`);
  const width = side => evaluate(`document.querySelector('.sidebar-panel.${side}').getBoundingClientRect().width`);
  const drag = async (side, delta) => {
    const p=await point(`#${side}-sidebar-resize`);
    await send('Input.dispatchMouseEvent',{type:'mousePressed',...p,button:'left',clickCount:1});
    await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:p.x+delta,y:p.y,button:'left',buttons:1});
    await send('Input.dispatchMouseEvent',{type:'mouseReleased',x:p.x+delta,y:p.y,button:'left',clickCount:1});
  };
  const shot = async name => {const r=await send('Page.captureScreenshot');fs.writeFileSync(path.join(output,name),Buffer.from(r.data,'base64'));};
  const app = new URL(appURL), token = new URLSearchParams(app.hash.slice(1)).get('token');
  assert.ok(token, 'Use a test backend token');
  const api = async (suffix, method='GET') => {
    const result = await fetch(app.origin + suffix, {method,headers:{Authorization:'Bearer '+token}});
    assert.ok(result.ok, `${method} ${suffix}: ${result.status}`);
    return result.json();
  };
  try {
    assert.deepEqual(await api('/api/labs'), [], 'Use an empty isolated test data directory');
    await send('Page.enable'); await send('Runtime.enable');
    await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
    await send('Page.navigate',{url:appURL});
    await wait('document.querySelectorAll(".topology-node").length===5');
    await evaluate('localStorage.removeItem("route-ovs-sidebars")');
    for (const side of ['left','right']) await evaluate(`document.querySelector('#${side}-sidebar-resize').dispatchEvent(new MouseEvent('dblclick',{bubbles:true}))`);

    // Cancel and invalid input must not replace the original canvas.
    await click('#new-lab'); await wait('document.querySelector("#project-name-dialog").open');
    await click('.project-name-cancel'); await wait('!document.querySelector("#project-name-dialog").open');
    assert.equal(await evaluate('document.querySelectorAll(".topology-node").length'),5);
    await click('#new-lab'); await wait('document.querySelector("#project-name-dialog").open');
    await input('#project-name-input','   '); await click('#confirm-project-name');
    await wait('!!document.querySelector("#project-name-error")');
    assert.equal(await evaluate('document.querySelectorAll(".topology-node").length'),5);
    await input('#project-name-input','  OSPF 中文项目  '); await click('#confirm-project-name');
    await wait('!document.querySelector("#project-name-dialog").open');
    assert.equal(await evaluate('document.querySelectorAll(".topology-node").length'),0);
    assert.ok(await evaluate('document.querySelector("#lab-name").textContent.includes("OSPF 中文项目")'));
    assert.ok(await evaluate('document.querySelector("#lab-select").selectedOptions[0].textContent.includes("OSPF 中文项目")'));
    await click('.device-card.router'); await click('#save'); await wait('document.querySelector("#save-state").textContent==="已保存"');
    savedId=await evaluate('document.querySelector("#lab-select").value');
    assert.equal((await api('/api/labs/'+savedId)).topology.name,'OSPF 中文项目');

    // Sidebar operations do not mark a saved topology dirty.
    await drag('left',90); await drag('right',-80);
    assert.equal(await width('left'),330); assert.equal(await width('right'),360);
    for (const side of ['left','right']) {await click(`#toggle-${side}-sidebar`);assert.equal(await width(side),36);await click(`#toggle-${side}-sidebar`);}
    assert.equal(await width('left'),330);assert.equal(await width('right'),360);
    assert.equal(await evaluate('document.querySelector("#save-state").textContent'),'已保存');
    await evaluate('document.querySelector("#right-sidebar-resize").dispatchEvent(new KeyboardEvent("keydown",{key:"ArrowLeft",bubbles:true}))');
    assert.equal(await width('right'),370,'right separator moves left to grow');
    await evaluate('document.querySelector("#left-sidebar-resize").dispatchEvent(new MouseEvent("dblclick",{bubbles:true}))');
    assert.equal(await width('left'),240);
    await drag('left',90);

    // Inspector contents remain mounted while hidden, including invalid drafts.
    await input('#node-name','invalid draft!');
    await click('#toggle-right-sidebar'); await click('#toggle-right-sidebar');
    assert.equal(await evaluate('document.querySelector("#node-name").value'),'invalid draft!');
    await click('#lab-name'); await wait('document.querySelector("#project-name-dialog").open');
    await input('#project-name-input','  已改名的实验  '); await click('#confirm-project-name');
    await wait('!document.querySelector("#project-name-dialog").open');
    assert.equal(await evaluate('document.querySelector("#node-name").value'),'invalid draft!','rename preserves properties');
    assert.ok(await evaluate('document.querySelector("#save-state").textContent.includes("未保存")'));
    assert.equal((await api('/api/labs/'+savedId)).topology.name,'已改名的实验');
    assert.equal((await api('/api/labs/'+savedId)).topology.nodes[0].name,'R1','rename does not save invalid property draft');
    await input('#node-name','R1'); await click('#save'); await wait('document.querySelector("#save-state").textContent==="已保存"');
    await click('#toggle-left-sidebar');
    await send('Page.reload'); await wait('document.querySelectorAll(".topology-node").length===1');
    assert.equal(await width('left'),36); assert.equal(await width('right'),370);
    assert.ok(await evaluate('document.querySelector("#lab-name").textContent.includes("已改名的实验")'));
    await click('#toggle-left-sidebar');assert.equal(await width('left'),330);
    assert.equal(await evaluate('document.querySelector("#lab-select").value'),savedId);

    // Resizing the viewport constrains both sidebars without losing preferences.
    await send('Emulation.setDeviceMetricsOverride',{width:1000,height:768,deviceScaleFactor:1,mobile:false});
    await wait('document.querySelector(".stage").clientWidth>=460 && document.documentElement.scrollWidth<=innerWidth');
    await drag('left',-500); await drag('right',500);
    assert.equal(await width('left'),200);assert.equal(await width('right'),240);
    await drag('left',500);
    assert.ok(await width('left')<=300);
    assert.equal(await evaluate('document.documentElement.classList.contains("resizing-sidebar")'),false);
    await shot('sidebars-narrow.png');
    await click('#toggle-left-sidebar');await click('#toggle-right-sidebar');
    await shot('sidebars-collapsed.png');
    await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
    await click('#toggle-left-sidebar');await click('#toggle-right-sidebar');
    for (const side of ['left','right']) await evaluate(`document.querySelector('#${side}-sidebar-resize').dispatchEvent(new MouseEvent('dblclick',{bubbles:true}))`);
    await shot('project-named.png');
    await click('#lab-name');await wait('document.querySelector("#project-name-dialog").open');
    await input('#project-name-input','取消的名称');await click('.project-name-cancel');
    assert.equal((await api('/api/labs/'+savedId)).topology.name,'已改名的实验');
    assert.deepEqual(errors,[],'browser exceptions');
    console.log(JSON.stringify({ok:true,checks:['new project name and cancellation','whitespace validation','save and reload Chinese name','same ID after rename','rename preserves unsaved properties','left/right drag and keyboard','collapse preserves width and draft','browser preference persistence','viewport constraints and no horizontal overflow','no dirty topology from layout changes'],screenshots:output},null,2));
  } finally {
    if(savedId) await api('/api/labs/'+savedId,'DELETE');
    ws.close();
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
