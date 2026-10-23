/* Browser integration check using Chromium's DevTools protocol and Node 22+.
 * Use an isolated --preview data directory. This creates and deletes a test lab.
 * node tests/check_workbench.cjs http://127.0.0.1:9338 http://127.0.0.1:8097/#token=... OUTPUT_DIR
 */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const [debugURL, appURL, outputDirectory] = process.argv.slice(2);
if (!debugURL || !appURL || !outputDirectory) throw Error('Expected DEBUG_URL APP_URL OUTPUT_DIRECTORY');

(async () => {
  fs.mkdirSync(outputDirectory, {recursive:true});
  const targets = await (await fetch(debugURL + '/json')).json();
  const target = targets.find(item => item.type === 'page');
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise(resolve => ws.addEventListener('open',resolve,{once:true}));
  let id=0;
  let acceptNextDialog=true, deleteRequests=0;
  const pending=new Map(), errors=[];
  const send=(method,params={})=>new Promise((resolve,reject)=>{
    const key=++id, timer=setTimeout(()=>{pending.delete(key);reject(Error('Timed out: '+method));},15000);
    pending.set(key,{resolve,reject,timer});ws.send(JSON.stringify({id:key,method,params}));
  });
  ws.addEventListener('message',event=>{
    const message=JSON.parse(event.data);
    if(pending.has(message.id)){const item=pending.get(message.id);clearTimeout(item.timer);pending.delete(message.id);message.error?item.reject(Error(JSON.stringify(message.error))):item.resolve(message.result);}
    if(message.method==='Runtime.exceptionThrown')errors.push(message.params.exceptionDetails.text+': '+(message.params.exceptionDetails.exception?.description||''));
    if(message.method==='Page.javascriptDialogOpening'){
      const accept=acceptNextDialog; acceptNextDialog=true;
      send('Page.handleJavaScriptDialog',{accept}).catch(()=>{});
    }
    if(message.method==='Network.requestWillBeSent'&&message.params.request.method==='DELETE')deleteRequests++;
  });
  const evaluate=async expression=>{
    const result=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    if(result.exceptionDetails)throw Error(result.exceptionDetails.exception?.description||result.exceptionDetails.text);
    return result.result.value;
  };
  const waitFor=async expression=>{for(let i=0;i<80;i++){if(await evaluate(expression))return;await new Promise(resolve=>setTimeout(resolve,100));}throw Error('Condition not met: '+expression+'; toast='+await evaluate('document.querySelector("#toast")?.textContent'));};
  const click=async selector=>{
    const point=await evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});if(!el)throw Error('Missing element');el.scrollIntoView({block:'nearest'});const r=el.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()`);
    await send('Input.dispatchMouseEvent',{type:'mousePressed',...point,button:'left',clickCount:1});
    await send('Input.dispatchMouseEvent',{type:'mouseReleased',...point,button:'left',clickCount:1});
  };
  const screenshot=async filename=>{const shot=await send('Page.captureScreenshot');fs.writeFileSync(path.join(outputDirectory,filename),Buffer.from(shot.data,'base64'));};
  await send('Page.enable');await send('Runtime.enable');await send('Network.enable');
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
  const freshURL = new URL(appURL);
  const accessToken = new URLSearchParams(freshURL.hash.slice(1)).get('token');
  assert.ok(accessToken, 'APP_URL must include #token=...');
  freshURL.searchParams.set('browser_check',Date.now());
  freshURL.hash = 'token=invalid-browser-test-token';
  await send('Page.navigate',{url:freshURL.toString()});
  await waitFor('document.querySelector("#access-dialog")?.open');
  await evaluate(`document.querySelector('#access-token').value=${JSON.stringify(accessToken)};document.querySelector('#access-token').dispatchEvent(new Event('input',{bubbles:true}))`);
  await click('#access-form button[type=submit]');
  await waitFor('!document.querySelector("#access-dialog").open');
  await waitFor('document.querySelectorAll(".topology-node").length===5');
  await waitFor('document.querySelector(".brand-mark")?.naturalWidth > 0');
  assert.equal(await evaluate('document.querySelector(".brand-mark").alt'),'北极熊头像');
  assert.equal(await evaluate('document.querySelector(".brand").textContent.includes(">")'),false,'brand must not render stray markup');
  assert.equal(await evaluate('fetch(document.querySelector("link[rel=icon]").href).then(async response=>response.ok&&(await response.text()).includes("北极熊"))'),true,'polar bear favicon is served');
  assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'),true,'horizontal overflow');
  assert.equal(await evaluate('document.querySelector("#deploy").disabled'),true,'preview must disable deployment');
  await click('#refresh');
  await waitFor('document.querySelector("#toast").textContent.includes("已刷新")');
  await click('.topology-node[data-node=r1] .node-name');
  await evaluate('document.querySelector("#node-name").value="invalid name!";document.querySelector("#node-name").dispatchEvent(new Event("input",{bubbles:true}))');
  acceptNextDialog=false;
  await click('#delete-current-lab');
  assert.equal(await evaluate('document.querySelectorAll(".topology-node").length'),5,'cancel deletion preserves unsaved lab');
  assert.equal(await evaluate('document.querySelector("#node-name").value'),'invalid name!','cancel preserves inspector draft');
  await click('#delete-current-lab');
  await waitFor('document.querySelectorAll(".topology-node").length===0');
  assert.equal(deleteRequests,0,'discarding a draft does not call DELETE');
  assert.equal(await evaluate('document.querySelector("#lab-select").selectedOptions[0].textContent'),'空白画布','deleted draft no longer appears as an unsaved experiment');
  assert.equal(await evaluate('document.querySelector("#save-state").textContent'),'未保存','discard clears unsaved-change status');
  assert.equal(await evaluate('document.querySelector("#delete-current-lab").disabled'),true,'empty canvas is not a deletable draft');
  assert.equal(await evaluate('document.querySelector("#delete-lab").disabled'),true,'inspector deletion also reflects empty state');
  await click('#new-lab');
  await click('#delete-lab');
  await waitFor('document.querySelector("#delete-lab").disabled');
  assert.equal(deleteRequests,0,'inspector can discard a new unsaved experiment locally');
  await click('#example');
  await waitFor('document.querySelectorAll(".topology-node").length===5');
  await screenshot('workbench.png');

  const panelHeight = () => evaluate('document.querySelector("#panel-body").getBoundingClientRect().height');
  const dragPanel = async delta => {
    const point = await evaluate('(()=>{const r=document.querySelector("#panel-resize-handle").getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()');
    await send('Input.dispatchMouseEvent',{type:'mousePressed',...point,button:'left',clickCount:1});
    await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:point.x,y:point.y-delta,button:'left',buttons:1});
    await send('Input.dispatchMouseEvent',{type:'mouseReleased',x:point.x,y:point.y-delta,button:'left',clickCount:1});
  };
  await evaluate('document.querySelector("#panel-resize-handle").dispatchEvent(new MouseEvent("dblclick",{bubbles:true}))');
  const initialPanelHeight = await panelHeight();
  const initialCanvasHeight = await evaluate('document.querySelector("#canvas-wrap").getBoundingClientRect().height');
  await dragPanel(120);
  assert.equal(await panelHeight(),initialPanelHeight+120,'dragging up enlarges output panel');
  assert.equal(await evaluate('document.querySelector("#canvas-wrap").getBoundingClientRect().height'),initialCanvasHeight-120,'canvas gives space to the output panel');
  await dragPanel(-80);
  assert.equal(await panelHeight(),initialPanelHeight+40,'dragging down shrinks output panel');
  await evaluate('document.querySelector("#panel-resize-handle").dispatchEvent(new KeyboardEvent("keydown",{key:"ArrowUp",bubbles:true}))');
  assert.equal(await panelHeight(),initialPanelHeight+64,'keyboard adjustment');
  await evaluate('document.querySelector("#panel-resize-handle").dispatchEvent(new KeyboardEvent("keydown",{key:"Home",bubbles:true}))');
  assert.equal(await panelHeight(),96,'minimum output height');
  await evaluate('document.querySelector("#panel-resize-handle").dispatchEvent(new KeyboardEvent("keydown",{key:"End",bubbles:true}))');
  assert.ok(await evaluate('document.querySelector("#canvas-wrap").getBoundingClientRect().height>=280'),'canvas minimum height');
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:760,deviceScaleFactor:1,mobile:false});
  await waitFor('document.querySelector(".bottom-panel").getBoundingClientRect().bottom<=innerHeight+1');
  assert.ok(await evaluate('document.querySelector("#canvas-wrap").getBoundingClientRect().height>=280'),'resizing window preserves canvas');
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
  await evaluate('document.querySelector("#panel-resize-handle").dispatchEvent(new MouseEvent("dblclick",{bubbles:true}))');
  assert.equal(await panelHeight(),initialPanelHeight,'double click resets height');
  await dragPanel(120);
  const preferredPanelHeight = await panelHeight();
  await click('#console-tab');
  assert.equal(await panelHeight(),preferredPanelHeight,'tab switch preserves height');
  assert.ok(await evaluate('document.querySelector("#terminal-empty").getBoundingClientRect().height>150'),'terminal fills the enlarged panel');
  assert.equal(await evaluate('document.querySelector("#open-terminal").disabled'),true,'preview disables terminal');
  await screenshot('workbench-console-large.png');
  await click('#toggle-panel');
  assert.equal(await panelHeight(),0,'collapse');
  await click('#toggle-panel');
  assert.equal(await panelHeight(),preferredPanelHeight,'expand restores height');
  assert.equal(await evaluate('document.documentElement.classList.contains("resizing-panel")'),false,'drag cursor is released');
  await click('#logs-tab');
  await click('#fit');

  const nodeBounds = () => evaluate(`(()=>{
    const node=document.querySelector('.topology-node[data-node=r1]');
    const body=node.querySelector('.node-body'), transform=node.transform.baseVal.consolidate().matrix;
    return {x:transform.e,y:transform.f,width:+body.getAttribute('width'),height:+body.getAttribute('height')};
  })()`);
  const dragDeviceHandle = async (handle, dx, dy) => {
    const point = await evaluate(`(()=>{
      const rect=document.querySelector('.topology-node[data-node=r1] [data-resize=${handle}] .node-resize-grip').getBoundingClientRect();
      return {x:rect.x+rect.width/2,y:rect.y+rect.height/2,scale:document.querySelector('#viewport').transform.baseVal.consolidate().matrix.a};
    })()`);
    await send('Input.dispatchMouseEvent',{type:'mousePressed',x:point.x,y:point.y,button:'left',clickCount:1});
    await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:point.x+dx*point.scale,y:point.y+dy*point.scale,button:'left',buttons:1});
    await send('Input.dispatchMouseEvent',{type:'mouseReleased',x:point.x+dx*point.scale,y:point.y+dy*point.scale,button:'left',clickCount:1});
    assert.equal(await evaluate('document.querySelector("#canvas").classList.contains("resizing-device")'),false,'resize cursor released');
  };
  await click('.topology-node[data-node=r1] .node-name');
  assert.equal(await evaluate('document.querySelectorAll("[data-resize]").length'),8,'selected editable device has eight handles');
  const originalBounds = await nodeBounds();
  await evaluate('window.resizeTestNode = document.querySelector(".topology-node[data-node=r1]")');
  for (const handle of ['n','s','e','w','ne','nw','se','sw']) {
    const horizontal=handle.includes('e')?1:handle.includes('w')?-1:0;
    const vertical=handle.includes('s')?1:handle.includes('n')?-1:0;
    await dragDeviceHandle(handle,horizontal*24,vertical*20);
    assert.deepEqual(await nodeBounds(),{
      x:originalBounds.x+horizontal*12,y:originalBounds.y+vertical*10,
      width:originalBounds.width+(horizontal?24:0),height:originalBounds.height+(vertical?20:0),
    },handle+' grows with the opposite edge fixed');
    await dragDeviceHandle(handle,-horizontal*24,-vertical*20);
    assert.deepEqual(await nodeBounds(),originalBounds,handle+' shrinks back');
  }
  assert.equal(await evaluate('window.resizeTestNode === document.querySelector(".topology-node[data-node=r1]")'),true,'resize preserves the Vue node');
  await click('#zoom-out');
  await dragDeviceHandle('se',72,60);
  let sized = await nodeBounds();
  assert.equal(sized.width,200,'resizing at a different zoom uses canvas coordinates');
  assert.equal(sized.height,160);
  assert.equal(await evaluate(`(()=>{
    const node=document.querySelector('.topology-node[data-node=r1]'), port=node.querySelector('[data-port=eth0]');
    const t=node.transform.baseVal.consolidate().matrix;
    const start=document.querySelector('.edge[data-link=l1] .wire').getAttribute('d').match(/^M ([0-9.-]+) ([0-9.-]+)/);
    return start && +start[1]===t.e+(+port.getAttribute('cx')) && +start[2]===t.f+(+port.getAttribute('cy'));
  })()`),true,'wire stays attached to the resized port');
  await screenshot('workbench-device-resized.png');
  await click('#reset-node-size');
  assert.deepEqual(await nodeBounds(),{...sized,width:128,height:100},'reset preserves device center');
  await click('#fit');
  await dragDeviceHandle('w',1000,0);
  await dragDeviceHandle('n',0,1000);
  assert.equal((await nodeBounds()).width,96,'minimum device width');
  assert.equal((await nodeBounds()).height,72,'minimum device height');
  await click('#reset-node-size');
  await dragDeviceHandle('se',72,60);
  await evaluate('document.querySelector("[data-resize=e]").focus()');
  await send('Input.dispatchKeyEvent',{type:'keyDown',key:'ArrowRight',code:'ArrowRight',windowsVirtualKeyCode:39});
  await send('Input.dispatchKeyEvent',{type:'keyUp',key:'ArrowRight',code:'ArrowRight',windowsVirtualKeyCode:39});
  assert.equal((await nodeBounds()).width,206,'keyboard resize');
  const savedBounds = await nodeBounds();
  await click('#connect-tool');
  assert.equal(await evaluate('document.querySelectorAll("[data-resize]").length'),0,'connection mode hides handles');
  await click('#select-tool');
  await click('#fit');

  await click('.device-card.host');
  await waitFor('document.querySelectorAll(".topology-node").length===6');
  await evaluate('document.querySelector("#node-name").value="PC_TEST";document.querySelector("#node-name").dispatchEvent(new Event("input",{bubbles:true}))');
  await click('#node-form button[type=submit]');
  assert.equal(await evaluate('[...document.querySelectorAll(".node-name")].some(el=>el.textContent==="PC_TEST")'),true);
  const before=await evaluate('document.querySelector(".topology-node[data-node=pc3]").getAttribute("transform")');
  await evaluate('window.browserTestNode = document.querySelector(".topology-node[data-node=pc3]")');
  const point=await evaluate('(()=>{const r=document.querySelector(".topology-node[data-node=pc3] .node-body").getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()');
  await send('Input.dispatchMouseEvent',{type:'mousePressed',...point,button:'left',clickCount:1});
  await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:point.x+80,y:point.y-80,button:'left',buttons:1});
  await send('Input.dispatchMouseEvent',{type:'mouseReleased',x:point.x+80,y:point.y-80,button:'left',clickCount:1});
  assert.notEqual(await evaluate('document.querySelector(".topology-node[data-node=pc3]").getAttribute("transform")'),before,'node must move');
  assert.equal(await evaluate('window.browserTestNode === document.querySelector(".topology-node[data-node=pc3]")'),true,'drag should update the existing Vue node');
  await click('.topology-node[data-node=sw1] .port[data-port=eth2]');
  await click('.topology-node[data-node=pc3] .port[data-port=eth0]');
  assert.equal(await evaluate('document.querySelectorAll(".edge").length'),5,'new cable');
  await click('.topology-node[data-node=pc3] .port[data-port=eth0]');
  assert.equal(await evaluate('document.querySelectorAll(".edge").length'),5,'occupied port cannot be reused');
  assert.equal(await evaluate('document.querySelector("#toast").textContent.includes("已经连接")'),true);
  await click('.topology-node[data-node=pc3] .node-name');
  await evaluate('document.querySelector("#node-name").value="PC_SAVED";document.querySelector("#node-name").dispatchEvent(new Event("input",{bubbles:true}))');
  await click('#save');
  await waitFor('document.querySelector("#save-state").textContent==="已保存"');
  const savedId=await evaluate('document.querySelector("#lab-select").value');
  await send('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:path.resolve(outputDirectory)});
  await click('#export');
  const exported=path.join(outputDirectory,savedId+'.json');
  for(let i=0;i<50&&!fs.existsSync(exported);i++)await new Promise(resolve=>setTimeout(resolve,100));
  const saved=JSON.parse(fs.readFileSync(exported,'utf8'));
  assert.equal(saved.nodes.length,6);assert.equal(saved.links.length,5);
  assert.equal(saved.nodes.find(node=>node.id==='pc3').name,'PC_SAVED','Save must include pending inspector edits');
  const exportedRouter = saved.nodes.find(node=>node.id==='r1');
  for (const key of ['x','y','width','height']) assert.equal(exportedRouter[key],savedBounds[key],'export preserves '+key);
  assert.equal(await evaluate('[...document.querySelector("#lab-select").options].some(option=>option.value==="")'),false,'saved experiments do not show a phantom unsaved option');
  const doc=await send('DOM.getDocument');
  const input=await send('DOM.querySelector',{nodeId:doc.root.nodeId,selector:'#import-file'});
  await send('DOM.setFileInputFiles',{nodeId:input.nodeId,files:[path.resolve(exported)]});
  await waitFor('document.querySelector("#toast").textContent.includes("已导入")');
  await click('#delete-current-lab');
  await waitFor('document.querySelectorAll(".topology-node").length===0');
  assert.equal(deleteRequests,0,'discarding an imported same-ID draft preserves the saved experiment');
  assert.equal(await evaluate(`!!document.querySelector('#lab-select option[value="${savedId}"]')`),true,'saved original stays in the list');
  await evaluate(`document.querySelector('#lab-select').value=${JSON.stringify(savedId)};document.querySelector('#lab-select').dispatchEvent(new Event('change',{bubbles:true}))`);
  await waitFor('document.querySelectorAll(".topology-node").length===6');
  assert.deepEqual(await nodeBounds(),savedBounds,'saved original remains loadable after deleting its imported draft');
  await send('DOM.setFileInputFiles',{nodeId:input.nodeId,files:[path.resolve(exported)]});
  await waitFor('document.querySelector("#toast").textContent.includes("已导入")');
  await click('#save');await waitFor('document.querySelector("#save-state").textContent==="已保存"');
  await send('Page.reload');
  await waitFor('[...document.querySelectorAll(".node-name")].some(el=>el.textContent==="PC_SAVED")');
  assert.equal(await panelHeight(),preferredPanelHeight,'panel height survives reload');
  assert.equal(await evaluate('document.querySelectorAll(".edge").length'),5,'links survive reload');
  assert.deepEqual(await nodeBounds(),savedBounds,'device dimensions survive save, import and reload');
  await screenshot('workbench-edited.png');

  // Delete the saved test lab through the same UI, leaving a fresh example.
  await click('#delete-lab');
  await waitFor('document.querySelectorAll(".topology-node").length===0');
  assert.equal(deleteRequests,1,'only deleting the saved experiment reaches the server');
  assert.equal(await evaluate(`!!document.querySelector('#lab-select option[value="${savedId}"]')`),false,'deleted saved experiment leaves the list');
  await click('#empty-example');
  await waitFor('document.querySelectorAll(".topology-node").length===5');
  await evaluate('document.querySelector("#panel-resize-handle").dispatchEvent(new MouseEvent("dblclick",{bubbles:true}))');
  await click('#fit');
  await screenshot('workbench.png');
  await click('.topology-node[data-node=r1] .node-name');
  await screenshot('workbench-properties.png');
  assert.deepEqual(errors,[],'browser JavaScript errors');
  console.log(JSON.stringify({ok:true,checks:['token authentication dialog','polar bear brand and favicon','initial topology','preview deployment disabled','environment refresh','cancel draft deletion preserves invalid properties','delete unsaved experiment from library','clear draft state without server deletion','delete unsaved experiment from inspector','no phantom unsaved option for saved experiments','discard imported draft without deleting same-ID saved experiment','resize output panel in both directions','keyboard resize and bounds','resize window preserves canvas','reset panel height','command output fills panel','collapse and expand preserve height','panel height survives reload','eight device handles grow and shrink with fixed opposite edge','stable Vue node while resizing','device resize at different zoom','wire follows resized port','reset device size preserves position','minimum device dimensions','keyboard device resize','connection mode hides resize handles','device dimensions survive save export import and reload','add device','edit properties','drag device','stable Vue node while dragging','connect ports','reject occupied port','save pending inspector edits','export','import','reload persistence','delete saved lab and remove list entry'],screenshots:outputDirectory},null,2));
  ws.close();
})().catch(error=>{console.error(error);process.exit(1);});
