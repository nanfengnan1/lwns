const { openSavedLab } = require('./browser_projects.cjs');
/* Real Chromium + disposable Docker fixture. See serve_terminal_fixture.py. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const [debugURL, appURL, outputDirectory] = process.argv.slice(2);
(async () => {
  fs.mkdirSync(outputDirectory, {recursive:true});
  const target = await (await fetch(debugURL+'/json/new?about:blank', {method:'PUT'})).json();
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise(resolve=>ws.addEventListener('open',resolve,{once:true}));
  let id=0;
  const pending=new Map(), errors=[], channels=new Map(), requests=[];
  const send=(method,params={})=>new Promise((resolve,reject)=>{
    const key=++id, timer=setTimeout(()=>{pending.delete(key);reject(Error('Timeout '+method));},15000);
    pending.set(key,{resolve,reject,timer});ws.send(JSON.stringify({id:key,method,params}));
  });
  ws.addEventListener('message', event=>{
    const msg=JSON.parse(event.data), item=pending.get(msg.id);
    if(item){clearTimeout(item.timer);pending.delete(msg.id);msg.error?item.reject(Error(JSON.stringify(msg.error))):item.resolve(msg.result);}
    if(msg.method==='Runtime.exceptionThrown')errors.push(msg.params.exceptionDetails.exception?.description||msg.params.exceptionDetails.text);
    if(msg.method==='Network.requestWillBeSent')requests.push(msg.params.request.url);
    if(msg.method==='Page.javascriptDialogOpening')send('Page.handleJavaScriptDialog',{accept:true}).catch(()=>{});
    if(msg.method==='Network.webSocketCreated' && new URL(msg.params.url).pathname==='/api/terminal')channels.set(msg.params.requestId,{output:'',sent:[],closed:false});
    const channel=channels.get(msg.params?.requestId);
    if(channel&&msg.method==='Network.webSocketFrameReceived'){
      const frame=msg.params.response;
      if(frame.opcode===2)channel.output+=Buffer.from(frame.payloadData,'base64').toString();
    }
    if(channel&&msg.method==='Network.webSocketFrameSent'){
      try {channel.sent.push(JSON.parse(msg.params.response.payloadData));}catch{}
    }
    if(channel&&msg.method==='Network.webSocketClosed')channel.closed=true;
  });
  const evaluate=async expression=>{
    const result=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    if(result.exceptionDetails)throw Error(result.exceptionDetails.exception?.description||result.exceptionDetails.text);
    return result.result.value;
  };
  const wait=async check=>{for(let i=0;i<120;i++){if(await check())return;await new Promise(r=>setTimeout(r,100));}throw Error('Condition timed out: '+check);};
  const waitDOM=expression=>wait(()=>evaluate(expression));
  const click=async(selector,count=1)=>{
    const point=await evaluate(`(()=>{const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
    for(let n=1;n<=count;n++){
      await send('Input.dispatchMouseEvent',{type:'mousePressed',...point,button:'left',clickCount:n});
      await send('Input.dispatchMouseEvent',{type:'mouseReleased',...point,button:'left',clickCount:n});
    }
  };
  const command=async text=>{
    await send('Input.insertText',{text});
    await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,text:'\r'});
    await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});
  };
  const screenshot=async filename=>{
    const shot=await send('Page.captureScreenshot');fs.writeFileSync(path.join(outputDirectory,filename),Buffer.from(shot.data,'base64'));
  };
  await send('Page.enable');await send('Runtime.enable');await send('Network.enable');
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
  try {
    const freshURL=new URL(appURL);freshURL.searchParams.set('terminal_check',Date.now());
    await send('Page.navigate',{url:freshURL.toString()});
    await openSavedLab(evaluate, waitDOM, click);
    await waitDOM('document.querySelectorAll(".topology-node").length===2');
    assert.equal(requests.some(url=>/\/(DeviceTerminal|ImageManager|CaptureManager)-.*\.js/.test(url)),false,'optional features are absent from initial requests');
    await evaluate('document.querySelector("#panel-resize-handle").dispatchEvent(new MouseEvent("dblclick",{bubbles:true}))');
    await waitDOM('document.querySelector("#panel-body").getBoundingClientRect().height===174');
    await click('#fit');
    await click('.topology-node[data-node=r1] .node-body',2);
    await waitDOM('document.querySelector(".terminal-state")?.textContent==="已连接"');
    assert.ok(requests.some(url=>/\/DeviceTerminal-.*\.js/.test(url)),'terminal loads on first use');
    const router=[...channels.values()].at(-1);
    await wait(()=>router.output.includes('R1#'));
    await command('configure terminal');
    await wait(()=>router.output.includes('R1(config)#'));
    await command('router ospf');
    await wait(()=>router.output.includes('R1(config-router)#'));
    await command('end');
    await command('show ip route');
    await evaluate('[...document.querySelectorAll(".terminal-toolbar button")].find(b=>b.textContent.trim()==="Linux Shell").click()');
    await waitDOM('document.querySelectorAll(".terminal-tab").length===2 && document.querySelector(".terminal-state")?.textContent==="已连接"');
    const routerShell=[...channels.values()].at(-1);
    await wait(()=>routerShell.output.includes('#'));
    await command("printf 'ROUTER_SHELL=%s\\n' OK");
    await wait(()=>routerShell.output.includes('ROUTER_SHELL=OK'));
    await click('.terminal-tab:last-child .close-terminal');
    await waitDOM('document.querySelectorAll(".terminal-tab").length===1');
    await click('.topology-node[data-node=pc1] .node-body',2);
    await waitDOM('document.querySelectorAll(".terminal-tab").length===2 && document.querySelector(".terminal-state")?.textContent==="已连接"');
    const host=[...channels.values()].at(-1);
    await wait(()=>host.output.includes('#'));
    await command('cd /tmp');
    await command("printf 'BROWSER_DIR=%s\\n' \"$PWD\"");
    await wait(()=>host.output.includes('BROWSER_DIR=/tmp'));
    await command('ping 127.0.0.1');
    await wait(()=>host.output.includes('bytes from'));
    await send('Input.dispatchKeyEvent',{type:'keyDown',key:'c',code:'KeyC',windowsVirtualKeyCode:67,modifiers:2});
    await send('Input.dispatchKeyEvent',{type:'keyUp',key:'c',code:'KeyC',windowsVirtualKeyCode:67,modifiers:2});
    await wait(()=>host.output.includes('statistics'));
    await evaluate('document.querySelector("#panel-resize-handle").dispatchEvent(new KeyboardEvent("keydown",{key:"End",bubbles:true}))');
    await wait(()=>host.sent.filter(v=>v.type==='resize').length>=2);
    const dimensions=host.sent.filter(v=>v.type==='resize').at(-1);
    await click('#fit');
    await click('.device-terminal[data-terminal=pc1] .xterm-screen');
    await command('stty size');
    await wait(()=>host.output.includes(`${dimensions.rows} ${dimensions.cols}`));
    const connections=channels.size;
    await click('.terminal-tab:first-child [role=tab]');
    await command('show version');
    await wait(()=>router.output.includes('FRRouting'));
    assert.equal(channels.size,connections,'switching tabs preserves sockets');
    assert.equal(host.closed,false);
    await screenshot('terminal-router.png');
    await click('.terminal-tab:nth-child(2) [role=tab]');
    await click('#expand-panel');
    await waitDOM('document.querySelector(".terminal-screen").getBoundingClientRect().height===0 || document.querySelector(".bottom-panel.expanded")!==null');
    await wait(()=>host.sent.filter(v=>v.type==='resize').at(-1)?.rows>dimensions.rows);
    await screenshot('terminal-expanded.png');
    await click('#expand-panel');
    await click('#toggle-panel');
    assert.equal(host.closed,false,'collapse preserves session');
    await click('#toggle-panel');
    await click('.device-terminal[data-terminal=pc1] .xterm-screen');
    await command('exit');
    await waitDOM('document.querySelector(".terminal-state")?.textContent==="已断开"');
    await evaluate('[...document.querySelectorAll(".terminal-toolbar button")].find(b=>b.textContent.trim()==="重连").click()');
    await waitDOM('document.querySelector(".terminal-state")?.textContent==="已连接"');
    assert.equal(channels.size,connections+1,'reconnect opens fresh session');
    await screenshot('terminal-tabs.png');
    await click('.terminal-tab:nth-child(2) .close-terminal');
    await waitDOM('document.querySelectorAll(".terminal-tab").length===1');
    await click('.terminal-tab .close-terminal');
    await waitDOM('document.querySelectorAll(".terminal-tab").length===0');
    await wait(()=>[...channels.values()].every(c=>c.closed));
    assert.deepEqual(errors,[],'browser runtime errors');
    console.log(JSON.stringify({ok:true,checks:['double-click opens device','interactive FRR config','router Linux shell','multiple device tabs','shell cwd persists','streaming ping','Ctrl+C','PTY resize','tab switches preserve session','maximize and restore','collapse preserves connection','exit and reconnect','close tabs disconnects','no browser errors'],screenshots:outputDirectory},null,2));
  }catch(error){await screenshot('terminal-failure.png');console.error([...channels.values()]);throw error;}
  finally {ws.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
