/* UI-only fixture: simulated runtime and capture states, no Docker/SSH access. */
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '..'), sessions = [];
const port = Number(process.argv[2] || 18107);
const topology = {version: 1, id: 'capture-ui-check', name: '连线抓包界面验证', nodes: [
  {id:'pc1',name:'PC1',kind:'host',image:'alpine/vpcs:latest',template:'linux-host',x:250,y:220,ports:[{name:'eth0',address:'192.0.2.161/30'}],gateway:'',config:'',command:[]},
  {id:'pc2',name:'PC2',kind:'host',image:'alpine/vpcs:latest',template:'linux-host',x:550,y:220,ports:[{name:'eth0',address:'192.0.2.162/30'}],gateway:'',config:'',command:[]}
], links:[{id:'wire1',a:{node:'pc1',port:'eth0'},b:{node:'pc2',port:'eth0'}}]};
const runtime = {phase:'running',deployment:'ui-test',nodes:{pc1:{id:'fake1',name:'test-pc1',pid:1},pc2:{id:'fake2',name:'test-pc2',pid:2}},logs:[]};
const environment = {ready:true,preview:false,errors:[],images:['alpine/vpcs:latest']};
const catalog = [{id:'linux-host',template_id:'linux-host',title:'VPCS 终端',kind:'host',image:'alpine/vpcs:latest',ports:1,console:'sh',console_command:['sh'],capabilities:{save_config:false,startup_config:false}}];
http.createServer(async (req,res) => {
  const pathname = new URL(req.url, 'http://127.0.0.1').pathname;
  const json = (value, code=200) => {res.writeHead(code, {'Content-Type':'application/json'});res.end(JSON.stringify(value));};
  if (pathname.startsWith('/api/')) {
    if (req.headers.authorization !== 'Bearer capture-ui-check') return json({error:'unauthorized'},401);
    let body = ''; for await (const chunk of req) body += chunk;
    if (pathname === '/api/bootstrap') return json({catalog,environment,labs:[{id:topology.id,name:topology.name,nodes:2,phase:'running'}],example:topology});
    if (pathname === '/api/labs') return json([{id:topology.id,name:topology.name,nodes:2,phase:'running'}]);
    if (pathname === '/api/labs/' + topology.id + '/open') return json({topology,runtime,busy:false});
    if (pathname === '/api/environment') return json(environment);
    if (pathname === '/api/capture/capabilities') return json({available:true,error:'',max_sessions:8,max_duration:3600});
    if (pathname === '/api/labs/' + topology.id) return json({topology,runtime,busy:false});
    if (pathname === '/api/labs/' + topology.id + '/captures') {
      if (req.method === 'GET') return json(sessions);
      const input = JSON.parse(body), session = {id:crypto.randomUUID(),lab:topology.id,link:input.link,side:input.side,label:(input.side==='a'?'PC1':'PC2')+' / eth0',filter:input.filter,snaplen:input.snaplen,state:'waiting',bytes:0,error:'',logs:'',created_at:new Date().toISOString()};
      sessions.unshift(session); return json({session,ticket:'T'.repeat(43)},201);
    }
    if (pathname.startsWith('/api/labs/' + topology.id + '/captures/')) {
      const session = sessions.find(s => s.id === pathname.split('/').at(-1));
      if (session) session.state='stopped'; return json({ok:true});
    }
    return json({error:'unknown fixture API'},404);
  }
  if (pathname === '/test/ready' && req.method === 'POST') {
    const session=sessions[0]; session.state='ready';session.client={status:'launched',manual_auth:true,output_file:'C:\\Users\\Example\\lwns\\captures\\20261023-PC2-eth0\\capture.pcapng'};return json({ok:true});
  }
  if (pathname === '/test/connect' && req.method === 'POST') {
    const session=sessions[0]; session.state='running';session.bytes=4096;return json({ok:true});
  }
  const file = path.resolve(root,'web/dist',pathname==='/'?'index.html':'.'+pathname);
  if (!file.startsWith(path.resolve(root,'web/dist') + path.sep) || !fs.existsSync(file)) {res.writeHead(404);res.end();return;}
  const types={'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'};
  res.writeHead(200,{'Content-Type':types[path.extname(file)]||'application/octet-stream'});fs.createReadStream(file).pipe(res);
}).listen(port,'127.0.0.1',()=>console.log('UI fixture http://127.0.0.1:'+port+'/#token=capture-ui-check'));
