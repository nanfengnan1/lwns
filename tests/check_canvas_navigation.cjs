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
  const click=async selector=>{const p=await point(selector);for(const type of ['mousePressed','mouseReleased'])await send('Input.dispatchMouseEvent',{type,...p,button:'left',clickCount:1});};
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
  try {
    await send('Page.enable');await send('Runtime.enable');
    await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
    await send('Page.navigate',{url:appURL});
    await openSavedLab(evaluate, wait, click);
    await wait('document.querySelector("#phase")?.classList.contains("running")');
    await click('#fit');
    const original=await record();
    assert.equal(await evaluate('document.querySelector("#save").textContent.trim()'),'保存布局');
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
    assert.ok(await evaluate('document.querySelector("#node-name").matches(":disabled")'));
    for(const selector of ['#connect-tool','#add-annotation','#delete-selection']) assert.ok(await evaluate(`document.querySelector(${JSON.stringify(selector)}).disabled`));
    await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Delete',code:'Delete',windowsVirtualKeyCode:46});
    await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Delete',code:'Delete',windowsVirtualKeyCode:46});
    assert.equal(await evaluate('document.querySelectorAll(".topology-node").length'),5);
    const noteBefore=await evaluate('document.querySelector(".topology-annotation").getAttribute("transform")');
    await drag(await point('.annotation-body'),45,35);
    assert.notEqual(await evaluate('document.querySelector(".topology-annotation").getAttribute("transform")'),noteBefore);
    assert.ok(await evaluate('document.querySelector("#annotation-text").matches(":disabled")&&document.querySelector("#delete-annotation").disabled'));
    await click('#auto-align');await click('#optimize-links');
    await click('#save');await wait('document.querySelector("#save-state").textContent==="已保存"');
    const saved=await record();
    assert.deepEqual(saved.runtime,original.runtime,'layout must preserve deployment and runtime');
    assert.deepEqual(saved.topology.links,original.topology.links);
    for(const node of saved.topology.nodes){const old=original.topology.nodes.find(n=>n.id===node.id);assert.deepEqual(node,{...old,x:node.x,y:node.y});}
    assert.notDeepEqual(saved.topology.nodes.map(n=>[n.x,n.y]),original.topology.nodes.map(n=>[n.x,n.y]));
    assert.notDeepEqual(saved.topology.annotations[0],original.topology.annotations[0]);
    assert.equal(saved.topology.annotations[0].text,original.topology.annotations[0].text);
    assert.equal(saved.topology.optimizeLinks,false);
    await send('Page.reload');await openSavedLab(evaluate, wait, click);await wait('document.querySelector("#phase")?.classList.contains("running")');
    for(const node of saved.topology.nodes) assert.equal(await evaluate(`document.querySelector('.topology-node[data-node="${node.id}"]').getAttribute('transform')`),`translate(${node.x} ${node.y})`);
    const shot=await send('Page.captureScreenshot');fs.writeFileSync(path.join(output,'canvas-scroll-running.png'),Buffer.from(shot.data,'base64'));
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({ok:true,checks:['both native scrollbar thumbs','vertical and Shift horizontal wheel','Ctrl wheel zoom in/out at cursor','viewport remains fixed','navigation does not dirty topology','running node and annotation drag','running alignment and routing','settings/add/delete stay locked','layout API preserves runtime and settings','saved positions survive reload'],screenshots:output},null,2));
  } catch(error) {
    const shot=await send('Page.captureScreenshot');fs.writeFileSync(path.join(output,'failed.png'),Buffer.from(shot.data,'base64'));
    console.error(await evaluate('(()=>{const e=document.querySelector("#canvas-scroll");return {width:innerWidth,height:innerHeight,x:e.scrollLeft,y:e.scrollTop,w:e.clientWidth,h:e.clientHeight,sw:e.scrollWidth,sh:e.scrollHeight}})()'));
    throw error;
  } finally {ws.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
