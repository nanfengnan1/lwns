/* Chromium CDP acceptance for serve_device_package_fixture.py; simulated Docker only.
 * node tests/check_device_packages.cjs DEBUG_URL APP_URL_WITH_TOKEN OUTPUT_DIR --fake-host
 */
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const [debugURL, appURL, output, flag] = process.argv.slice(2);
if (!debugURL || !appURL || !output || flag !== '--fake-host') throw Error('Expected DEBUG_URL APP_URL_WITH_TOKEN OUTPUT_DIR --fake-host');
(async () => {
  fs.mkdirSync(output,{recursive:true});
  const app=new URL(appURL), token=new URLSearchParams(app.hash.slice(1)).get('token');
  const target=await(await fetch(debugURL+'/json/new?about:blank',{method:'PUT'})).json();
  const ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise(resolve=>ws.addEventListener('open',resolve,{once:true}));
  let sequence=0;const pending=new Map(),errors=[],requests=[],checks=[];
  const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence,timer=setTimeout(()=>{pending.delete(id);reject(Error('CDP timeout: '+method));},20000);pending.set(id,{resolve,reject,timer});ws.send(JSON.stringify({id,method,params}));});
  ws.addEventListener('message',({data})=>{const message=JSON.parse(data),request=pending.get(message.id);if(request){clearTimeout(request.timer);pending.delete(message.id);message.error?request.reject(Error(JSON.stringify(message.error))):request.resolve(message.result);}if(message.method==='Runtime.exceptionThrown')errors.push(message.params.exceptionDetails.exception?.description||message.params.exceptionDetails.text);if(message.method==='Page.javascriptDialogOpening')void send('Page.handleJavaScriptDialog',{accept:true});if(message.method==='Network.requestWillBeSent'&&message.params.request.url.includes('/api/'))requests.push(message.params.request.url);});
  const evaluate=async expression=>{const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true,userGesture:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value;};
  const wait=async expression=>{for(let attempt=0;attempt<200;attempt++){if(await evaluate(expression))return;await new Promise(resolve=>setTimeout(resolve,100));}throw Error('Condition not met: '+expression+'; '+await evaluate('document.querySelector("#device-package-error")?.textContent+" / "+document.querySelector("#device-package-log")?.textContent+" / "+document.querySelector("#toast")?.textContent'));};
  const click=async selector=>{const location=await evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});if(!e||e.disabled)throw Error('Missing/disabled '+${JSON.stringify(selector)});e.scrollIntoView({block:'nearest'});const r=e.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}})()`);for(const type of ['mousePressed','mouseReleased'])await send('Input.dispatchMouseEvent',{type,...location,button:'left',clickCount:1});};
  const input=(selector,value)=>evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});e.value=${JSON.stringify(value)};e.dispatchEvent(new Event(e.tagName==='SELECT'?'change':'input',{bubbles:true}))})()`);
  const textFile=(selector,name,content)=>evaluate(`(()=>{const transfer=new DataTransfer();transfer.items.add(new File([${JSON.stringify(content)}],${JSON.stringify(name)},{type:'application/json'}));const e=document.querySelector(${JSON.stringify(selector)});e.files=transfer.files;e.dispatchEvent(new Event('change',{bubbles:true}))})()`);
  const api=async(route,method='GET',body)=>{const result=await fetch(app.origin+route,{method,headers:{Authorization:'Bearer '+token,...(body===undefined?{}:{'Content-Type':'application/json'})},...(body===undefined?{}:{body:JSON.stringify(body)})});const content=await result.json();if(!result.ok)throw Error(JSON.stringify(content));return content;};
  const shot=async name=>{const r=await send('Page.captureScreenshot');fs.writeFileSync(path.join(output,name),Buffer.from(r.data,'base64'));};
  const openManager=async()=>{await click('#menu-tools');await click('#menu-devices');await wait('document.querySelector("#device-package-manager")?.open');};
  let projectId,definitionId;
  try {
    await send('Page.enable');await send('Runtime.enable');await send('Network.enable');
    await send('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:path.resolve(output)});
    await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
    await send('Page.navigate',{url:appURL});await wait('!!document.querySelector("#menu-tools")&&!document.querySelector("#access-dialog")?.open');
    await openManager();await click('#device-tab-pack');
    const descriptor={schema_version:1,id:'browser-host',version:'1.0.0',name:'浏览器主机',category:'host',image:'alpine/vpcs:latest',source:{type:'repository'},console:['sh','-i'],persistent_dirs:[{id:'config',target:'/etc/lab',initialize_from:'empty'}],startup:{phase:'after_links',service:{exec:['sleep','infinity']},ready:{exec:['test','-d','/etc/lab']},config_files:['/etc/lab/startup.conf']},actions:{save_config:{exec:['/usr/local/bin/save-config']}}};
    await textFile('#device-descriptor-file','device.json',JSON.stringify(descriptor));await wait('document.querySelector("#device-package-name").value==="浏览器主机"');
    assert.equal(await evaluate('document.querySelector("#device-package-category").value'),'host');
    await input('#device-package-name','可分享主机');await shot('device-package-maker.png');await click('#pack-device-package');
    await wait('!!document.querySelector("#download-device-package")');
    const made=await api('/api/device-packages');assert.equal(made.devices.length,0,'making does not register a device');const packJob=made.jobs.find(job=>job.mode==='pack'&&job.state==='success');assert.ok(packJob?.result.path,'server artifact path is reported');
    await click('#download-device-package');const packagePath=path.join(output,packJob.result.filename);
    for(let i=0;i<100&&!fs.existsSync(packagePath);i++)await new Promise(resolve=>setTimeout(resolve,100));assert.ok(fs.existsSync(packagePath),'downloaded file exists');checks.push('Web maker downloads a .rov without registering it');
    await click('#device-tab-import');const document=await send('DOM.getDocument');const upload=await send('DOM.querySelector',{nodeId:document.root.nodeId,selector:'#device-package-file'});await send('DOM.setFileInputFiles',{nodeId:upload.nodeId,files:[packagePath]});
    await wait('!!document.querySelector("#device-package-import-name")&&!document.querySelector("#import-device-package").disabled');assert.equal(await evaluate('document.querySelector("#device-package-import-name").value'),'可分享主机');await input('#device-package-import-name','我的测试 PC');await shot('device-package-import.png');await click('#import-device-package');
    await wait('document.querySelector(".device-job-status")?.textContent==="已完成"&&!document.querySelector("#device-package-import-name")');
    const imported=await api('/api/device-packages');assert.equal(imported.devices.length,1);definitionId=imported.devices[0].id;assert.equal(imported.devices[0].name,'我的测试 PC');
    await click('#device-tab-library');await wait('document.querySelectorAll(".installed-device").length===1');await click('.device-entry-actions button');await input('#device-package-rename','重命名 PC');await click('.device-rename button[type=submit]');await wait('document.querySelector(".installed-device h3")?.textContent==="重命名 PC"');await shot('device-package-library.png');checks.push('inspect, name, import and rename use one immutable definition');
    await click('#close-device-packages');await click('[data-category=host]');await wait(`!!document.querySelector('.device-card[data-template="${definitionId}"]')`);await click(`.device-card[data-template="${definitionId}"]`);
    const instanceId=await evaluate('document.querySelector(".topology-node.selected").dataset.node');assert.match(instanceId,/^[0-9a-f]{32}$/);assert.equal(await evaluate('document.querySelector("#node-image").readOnly'),true);await click('.property-section summary');assert.equal(await evaluate('document.querySelector("#node-command").readOnly'),true);assert.equal(await evaluate('!!document.querySelector("#node-config")'),false);checks.push('managed node pins template, image and lifecycle without FRR-only editor');
    const created=await api('/api/labs','POST',{name:'设备包引用验收'});projectId=created.topology.id;created.topology.nodes=[{id:instanceId,name:'PC1',kind:'host',template:definitionId,image:imported.devices[0].image_id,ports:[{name:'eth0',address:''}],gateway:'',command:[],config:'',x:0,y:0}];await api('/api/labs/'+projectId,'PUT',created.topology);
    await openManager();await click('#device-tab-library');await click('.remove-device');await wait('document.querySelector("#device-package-error")?.textContent.includes("引用")');assert.equal((await api('/api/device-packages')).devices.length,1);checks.push('referenced definitions cannot be removed');
    await api('/api/labs/'+projectId,'DELETE');projectId=undefined;await click('.remove-device');await wait('document.querySelectorAll(".installed-device").length===0');await click('#close-device-packages');await wait(`!document.querySelector('.device-card[data-template="${definitionId}"]')`);assert.equal(await evaluate('document.querySelectorAll(".topology-node").length'),1,'library removal preserves the unsaved canvas');definitionId=undefined;checks.push('removal refreshes sidebar and preserves existing canvas');
    await openManager();await send('Emulation.setDeviceMetricsOverride',{width:1000,height:760,deviceScaleFactor:1,mobile:false});await click('#device-tab-pack');await shot('device-package-compact.png');
    assert.ok(await evaluate('(()=>{const d=document.querySelector("#device-package-manager"),r=d.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight&&d.scrollWidth<=d.clientWidth+1})()'),'manager fits a 1000px viewport');checks.push('compact viewport layout');
    assert.deepEqual(errors,[]);assert.ok(requests.every(url=>new URL(url).origin===app.origin));checks.push('all API requests stay same origin without runtime exceptions');
    fs.writeFileSync(path.join(output,'result.json'),JSON.stringify({checks,requests:requests.length},null,2));console.log(JSON.stringify({checks,requests:requests.length},null,2));
  } catch(error) {await shot('device-package-failed.png').catch(()=>{});throw error;}
  finally {if(projectId)await api('/api/labs/'+projectId,'DELETE').catch(()=>{});if(definitionId)await api('/api/device-packages/'+definitionId,'DELETE').catch(()=>{});ws.close();await fetch(debugURL+'/json/close/'+target.id).catch(()=>{});}
})().catch(error=>{console.error(error);process.exitCode=1;});
