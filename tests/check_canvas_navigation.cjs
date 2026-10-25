const { openSavedLab } = require('./browser_projects.cjs');
/* Requires serve_canvas_fixture.py (FakeHost only), Chromium CDP and Node 22+.
 * node tests/check_canvas_navigation.cjs DEBUG_URL APP_URL_WITH_TOKEN OUTPUT_DIR
 */
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const [debugURL, appURL, output] = process.argv.slice(2);
if (!debugURL || !appURL || !output) throw Error('Expected DEBUG_URL APP_URL OUTPUT_DIR');
(async () => {
  fs.mkdirSync(output, {recursive:true});
  const target = await (await fetch(debugURL+'/json/new?about:blank', {method:'PUT'})).json();
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise(resolve => ws.addEventListener('open', resolve, {once:true}));
  let seq=0;
  const pending=new Map(), errors=[];
  const send=(method,params={})=>new Promise((resolve,reject)=>{
    const id=++seq, timer=setTimeout(()=>{pending.delete(id);reject(Error('Timeout: '+method));},15000);
    pending.set(id,{resolve,reject,timer}); ws.send(JSON.stringify({id,method,params}));
  });
  ws.addEventListener('message',event=>{
    const m=JSON.parse(event.data), p=pending.get(m.id);
    if(p){clearTimeout(p.timer);pending.delete(m.id);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result);}
    if(m.method==='Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.exception?.description||m.params.exceptionDetails.text);
    if(m.method==='Page.javascriptDialogOpening') void send('Page.handleJavaScriptDialog',{accept:true});
  });
  const evaluate=async expression=>{
    const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    if(r.exceptionDetails) throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);
    return r.result.value;
  };
  const wait=async expression=>{
    for(let i=0;i<80;i++){if(await evaluate(expression))return;await new Promise(r=>setTimeout(r,100));}
    throw Error('Condition not met: '+expression+'; toast='+await evaluate('document.querySelector("#toast")?.textContent'));
  };
  const point=selector=>evaluate(`(()=>{const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}})()`);
  const click=async selector=>{await evaluate(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView({block:"nearest",inline:"nearest"})`);const p=await point(selector);for(const type of ['mousePressed','mouseReleased'])await send('Input.dispatchMouseEvent',{type,...p,button:'left',clickCount:1});};
  const drag=async(p,dx,dy)=>{
    await send('Input.dispatchMouseEvent',{type:'mousePressed',...p,button:'left',clickCount:1});
    await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:p.x+dx,y:p.y+dy,button:'left',buttons:1});
    await send('Input.dispatchMouseEvent',{type:'mouseReleased',x:p.x+dx,y:p.y+dy,button:'left',clickCount:1});
  };
  const view=()=>evaluate('(()=>{const m=document.querySelector("#viewport").transform.baseVal.consolidate().matrix;const r=document.querySelector("#canvas").getBoundingClientRect();return{x:m.e,y:m.f,scale:m.a,left:r.left,top:r.top}})()');
  const painted=()=>evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
  const wheel=async(p,dy,modifiers=0)=>send('Input.dispatchMouseEvent',{type:'mouseWheel',...p,deltaX:0,deltaY:dy,modifiers});
  const url=new URL(appURL),token=new URLSearchParams(url.hash.slice(1)).get('token');
  const record=async()=>{
    const r=await fetch(url.origin+'/api/labs/first-lab',{headers:{Authorization:'Bearer '+token}});
    assert.ok(r.ok);return r.json();
  };
  const savedState='["已保存","部分设备仅保存拓扑"].includes(document.querySelector("#save-state").textContent)';
  const sameDeployment=(after,before)=>{
    const {logs:afterLogs,...afterState}=after,{logs:beforeLogs,...beforeState}=before;
    assert.deepEqual(afterState,beforeState,'project save preserves deployment, phase and device identity');
    assert.deepEqual(afterLogs.slice(0,beforeLogs.length),beforeLogs,'existing deployment logs are retained');
  };
  try {
    await send('Page.enable');await send('Runtime.enable');
    await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
    await send('Page.navigate',{url:appURL});
    await openSavedLab(evaluate, wait, click);
    await wait('document.querySelector("#phase")?.classList.contains("running")');
    await click('#fit');
    const original=await record();
    assert.equal(await evaluate('document.querySelector("#save").textContent.trim()'),'保存项目');
    assert.ok(await evaluate('(()=>{const e=document.querySelector("#canvas-scroll");return e.scrollWidth>e.clientWidth&&e.scrollHeight>e.clientHeight&&getComputedStyle(e).overflowX==="scroll"&&getComputedStyle(e).overflowY==="scroll"})()'));
    const center=await point('#canvas');
    const before=await view();
    await wheel(center,100);
    await wait(`document.querySelector('#viewport').transform.baseVal.consolidate().matrix.f < ${before.y-80}`);
    const vertical=await view();
    assert.equal(vertical.scale,before.scale);assert.ok(Math.abs(vertical.left-before.left)<1&&Math.abs(vertical.top-before.top)<1,'SVG remains fixed in the viewport');
    await wheel(center,100,8);
    await wait(`document.querySelector('#viewport').transform.baseVal.consolidate().matrix.e < ${before.x-80}`);
    const horizontal=await view();
    assert.ok(Math.abs(horizontal.y-vertical.y)<1,'Shift wheel only pans horizontally');
    await wheel(center,-180,2);
    await wait(`document.querySelector('#viewport').transform.baseVal.consolidate().matrix.a > ${horizontal.scale+0.05}`);
    const zoomed=await view();
    for(const axis of ['x','y']){
      const origin=axis==='x'?'left':'top';
      assert.ok(Math.abs((center[axis]-horizontal[origin]-horizontal[axis])/horizontal.scale-(center[axis]-zoomed[origin]-zoomed[axis])/zoomed.scale)<1,'Ctrl zoom keeps cursor world coordinate');
    }
    await wheel(center,180,2);
    await wait(`Math.abs(document.querySelector('#viewport').transform.baseVal.consolidate().matrix.a-${horizontal.scale})<0.01`);
    // Drag each actual native scrollbar thumb, not the SVG or a simulated range input.
    for(const axis of ['x','y']){
      await click('#fit');
      await painted();
      const data=await evaluate(`(()=>{const e=document.querySelector('#canvas-scroll'),r=e.getBoundingClientRect();return {x:r.left+(${JSON.stringify(axis)}==='x'?(e.scrollLeft+e.clientWidth/2)/e.scrollWidth*e.clientWidth:e.clientWidth+7),y:r.top+(${JSON.stringify(axis)}==='y'?(e.scrollTop+e.clientHeight/2)/e.scrollHeight*e.clientHeight:e.clientHeight+7),offset:${JSON.stringify(axis)}==='x'?e.scrollLeft:e.scrollTop}})()`);
      await drag({x:data.x,y:data.y},axis==='x'?50:0,axis==='y'?50:0);
      await wait(`document.querySelector('#canvas-scroll').${axis==='x'?'scrollLeft':'scrollTop'} > ${data.offset+20}`);
    }
    assert.equal(await evaluate('document.querySelector("#save-state").textContent'),'已保存','navigation alone is not a topology change');
    await click('#fit');
    const nodeBefore=await evaluate('document.querySelector(".topology-node[data-node=r1]").getAttribute("transform")');
    await drag(await point('.topology-node[data-node=r1] .node-body'),80,35);
    assert.notEqual(await evaluate('document.querySelector(".topology-node[data-node=r1]").getAttribute("transform")'),nodeBefore);
    assert.equal(await evaluate('document.querySelector("#node-name").matches(":disabled")'),false,'deployed properties are editable');
    for(const selector of ['#connect-tool','#add-annotation','#delete-selection']) assert.equal(await evaluate(`document.querySelector(${JSON.stringify(selector)}).disabled`),false,'deployed editing is enabled');
    const noteBefore=await evaluate('document.querySelector(".topology-annotation").getAttribute("transform")');
    await drag(await point('.annotation-body'),45,35);
    assert.notEqual(await evaluate('document.querySelector(".topology-annotation").getAttribute("transform")'),noteBefore);
    assert.equal(await evaluate('document.querySelector("#annotation-text").matches(":disabled")||document.querySelector("#delete-annotation").disabled'),false);
    await evaluate('document.querySelector("#annotation-text").value="运行中可编辑注释";document.querySelector("#annotation-text").dispatchEvent(new Event("input",{bubbles:true}))');
    await click('#annotation-form button[type=submit]');
    await click('#auto-align');await click('#optimize-links');
    await click('#save');await wait('document.querySelector("#save-state").textContent==="部分设备仅保存拓扑"');
    const saved=await record();
    sameDeployment(saved.runtime,original.runtime);
    assert.ok(saved.runtime.logs.some(line=>line.message.includes('已保存设备配置: R1')),'project save captures supported FRR configuration');
    assert.deepEqual(saved.topology.links,original.topology.links);
    for(const node of saved.topology.nodes){const old=original.topology.nodes.find(n=>n.id===node.id);assert.deepEqual(node,{...old,x:node.x,y:node.y,config:node.id==='r1'?'!':old.config});}
    assert.notDeepEqual(saved.topology.nodes.map(n=>[n.x,n.y]),original.topology.nodes.map(n=>[n.x,n.y]));
    assert.notDeepEqual(saved.topology.annotations[0],original.topology.annotations[0]);
    assert.equal(saved.topology.annotations[0].text,"运行中可编辑注释");
    assert.equal(saved.topology.optimizeLinks,false);
    await send('Page.reload');await openSavedLab(evaluate, wait, click);await wait('document.querySelector("#phase")?.classList.contains("running")');
    for(const node of saved.topology.nodes) assert.equal(await evaluate(`document.querySelector('.topology-node[data-node="${node.id}"]').getAttribute('transform')`),`translate(${node.x} ${node.y})`);
    await click('[data-category=host]');
    await click('.device-card.host');
    await wait('!!document.querySelector(".topology-node[data-node=pc3]")');
    assert.equal(await evaluate('document.querySelector("#inspect-console").disabled'),true,'new draft device has no running terminal');
    await evaluate('document.querySelector("[data-address=eth0]").value="10.10.1.30/24";document.querySelector("[data-address=eth0]").dispatchEvent(new Event("input",{bubbles:true}));document.querySelector("#node-gateway").value="10.10.1.1";document.querySelector("#node-gateway").dispatchEvent(new Event("input",{bubbles:true}))');
    await click('#node-form button[type=submit]');
    await click('#fit');
    await drag(await point('.topology-node[data-node=pc3] .node-body'),-180,100);
    await click('#fit');
    await click('.topology-node[data-node=sw1] .port[data-port=eth2]');
    await click('.topology-node[data-node=pc3] .port[data-port=eth0]');
    await wait('document.querySelectorAll(".edge").length===5');
    const draft=await record();
    assert.deepEqual(draft.topology,saved.topology,'editing the canvas does not prematurely replace deployed topology');
    assert.equal(Object.keys(draft.runtime.nodes).length,5);
    await wait('document.querySelector("#save-state").textContent.includes("拓扑待应用")');
    await click('#apply-topology');
    await wait('document.querySelector("#phase").classList.contains("updating")');
    assert.ok(await evaluate('document.querySelector("#connect-tool").disabled&&document.querySelector("#add-annotation").disabled'),'editing locks while applying');
    await wait(savedState+'&&document.querySelector("#phase").classList.contains("running")');
    const applied=await record();
    assert.equal(applied.topology.nodes.length,6);assert.equal(applied.topology.links.length,5);
    assert.equal(applied.runtime.deployment,original.runtime.deployment);
    for(const [id,node] of Object.entries(original.runtime.nodes))assert.equal(applied.runtime.nodes[id].id,node.id,'unchanged container '+id+' is preserved');
    assert.ok(applied.runtime.nodes.pc3?.id);
    assert.equal(applied.topology.nodes.find(n=>n.id==='pc3').ports[0].address,'10.10.1.30/24');
    await click('.topology-node[data-node=pc3] .node-name');
    assert.equal(await evaluate('document.querySelector("#inspect-console").disabled'),false,'new device becomes available after application');
    // Address-only edits keep the existing container identity.
    await evaluate('document.querySelector("[data-address=eth0]").value="10.10.1.31/24";document.querySelector("[data-address=eth0]").dispatchEvent(new Event("input",{bubbles:true}))');
    await click('#node-form button[type=submit]');await click('#apply-topology');
    await wait(savedState+'&&document.querySelector("#phase").classList.contains("running")');
    const readdressed=await record();
    assert.equal(readdressed.runtime.nodes.pc3.id,applied.runtime.nodes.pc3.id);
    assert.equal(readdressed.topology.nodes.find(n=>n.id==='pc3').ports[0].address,'10.10.1.31/24');
    // Adding and deleting notes are visual saves, including after deployment.
    await click('#add-annotation');
    const notePoint=await evaluate('(()=>{const r=document.querySelector("#canvas").getBoundingClientRect();return{x:r.left+65,y:r.top+120}})()');
    for(const type of ['mousePressed','mouseReleased'])await send('Input.dispatchMouseEvent',{type,...notePoint,button:'left',clickCount:1});
    await wait('document.querySelectorAll(".topology-annotation").length===2');
    const newNote=await evaluate('document.querySelector(".topology-annotation.selected").dataset.annotation');
    await click('#save');await wait(savedState);
    const noted=await record();assert.equal(noted.topology.annotations.length,2);sameDeployment(noted.runtime,readdressed.runtime);
    await click('#delete-annotation');await click('#save');await wait(savedState);
    const withoutNote=await record();assert.equal(withoutNote.topology.annotations.some(n=>n.id===newNote),false);sameDeployment(withoutNote.runtime,noted.runtime);
    // Deleting the device removes its cable in the draft; application removes owned resources.
    await click('.topology-node[data-node=pc3] .node-name');await click('#delete-selection');
    await wait('document.querySelectorAll(".topology-node").length===5&&document.querySelectorAll(".edge").length===4');
    assert.ok((await record()).runtime.nodes.pc3,'delete remains a draft before application');
    await click('#apply-topology');
    await wait(savedState+'&&document.querySelector("#phase").classList.contains("running")');
    const removed=await record();assert.equal(removed.runtime.nodes.pc3,undefined);assert.equal(removed.topology.nodes.length,5);assert.equal(removed.topology.links.length,4);
    for(const [id,node] of Object.entries(original.runtime.nodes))assert.equal(removed.runtime.nodes[id].id,node.id);
    await send('Page.reload');await openSavedLab(evaluate,wait,click);await wait('document.querySelector("#phase").classList.contains("running")');
    assert.equal(await evaluate('document.querySelectorAll(".topology-node").length'),5);assert.equal(await evaluate('document.querySelectorAll(".edge").length'),4);
    for (const node of removed.topology.nodes) {
      await click(`.topology-node[data-node="${node.id}"] .node-name`);
      await click('#delete-selection');
    }
    assert.equal(await evaluate('document.querySelectorAll(".topology-node").length'),0);
    assert.equal(await evaluate('document.querySelector("#apply-topology").disabled'),false,'an empty topology can be applied');
    await click('#apply-topology');await wait(savedState+'&&document.querySelector("#phase").classList.contains("running")');
    const empty=await record();assert.equal(empty.topology.nodes.length,0);assert.deepEqual(empty.runtime.nodes,{});assert.equal(empty.runtime.deployment,original.runtime.deployment);
    await click('[data-category=host]');await click('.device-card.host');
    await wait('document.querySelectorAll(".topology-node").length===1');
    await click('#apply-topology');await wait(savedState+'&&document.querySelector("#phase").classList.contains("running")');
    const restarted=await record();assert.equal(restarted.topology.nodes.length,1);assert.equal(Object.keys(restarted.runtime.nodes).length,1);assert.equal(restarted.runtime.deployment,original.runtime.deployment);
    const shot=await send('Page.captureScreenshot');fs.writeFileSync(path.join(output,'canvas-scroll-running.png'),Buffer.from(shot.data,'base64'));
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({ok:true,checks:['both native scrollbar thumbs','vertical and Shift horizontal wheel','Ctrl wheel zoom in/out at cursor','viewport remains fixed','navigation does not dirty topology','running node and annotation drag','running alignment and routing','deployed properties and notes editable','visual saves preserve runtime','saved positions survive reload','network drafts do not change deployed topology','apply locks editing and preserves unchanged containers','address edits preserve container identity','new devices activate terminal after apply','annotation add/delete use visual saves','device delete removes its cable only after apply','applied topology survives reload','apply an empty deployment and add devices again'],screenshots:output},null,2));
  } catch(error) {
    const shot=await send('Page.captureScreenshot');fs.writeFileSync(path.join(output,'failed.png'),Buffer.from(shot.data,'base64'));
    console.error(await evaluate('(()=>{const e=document.querySelector("#canvas-scroll");return {width:innerWidth,height:innerHeight,x:e.scrollLeft,y:e.scrollTop,w:e.clientWidth,h:e.clientHeight,sw:e.scrollWidth,sh:e.scrollHeight}})()'));
    throw error;
  } finally {ws.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
