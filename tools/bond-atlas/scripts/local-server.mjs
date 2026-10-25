import http from 'node:http';
import {readFile,writeFile,mkdir,rename,unlink} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {randomBytes} from 'node:crypto';
import {loadEuroBonds} from '../lib/euro-source.ts';
import {loadCurve,countryIds} from '../lib/sources.ts';

const root=fileURLToPath(new URL('../',import.meta.url));
const assets=path.join(root,'local-dist');
const runtime=path.join(root,'.sites-runtime','local-app');
const offline=process.argv.includes('--offline');
const port=8787,host='127.0.0.1';
const token=randomBytes(32).toString('hex');
const statePath=path.join(runtime,'server.json');
const cacheFile=key=>path.join(runtime,key+'.json');
await mkdir(runtime,{recursive:true});
await readFile(path.join(assets,'index.html')); // Fail before listening when the local build is missing.
const json=async filename=>JSON.parse(await readFile(filename,'utf8'));
const snapshots={bonds:await json(path.join(root,'lib','euro-snapshot.json')),curves:await json(path.join(root,'lib','snapshot.json'))};
const cache={},pending={},retryAfter={};
for(const key of ['bonds','curves']){try{const saved=await json(cacheFile(key));if(saved?.data&&(key==='bonds'?Array.isArray(saved.data.bonds):Array.isArray(saved.data.curves)))cache[key]=saved;}catch{}}
async function persist(key,data){
 cache[key]={time:Date.now(),data};
 try{const temp=cacheFile(key)+'.tmp';await writeFile(temp,JSON.stringify(cache[key]));await rename(temp,cacheFile(key));}catch(e){console.error('Impossibile salvare la rilevazione locale:',e.message)}
}
function fallback(key){
 const data=cache[key]?.data;
 return key==='bonds'?{...(data??snapshots.bonds),fallback:true}:{curves:(data?.curves??snapshots.curves).map(c=>({...c,fallback:true,error:'Aggiornamento non disponibile: rilevazione salvata.'}))};
}
async function dataFor(key){
 if(offline)return fallback(key);
 const ttl=key==='bonds'?6*60*60*1000:15*60*1000;
 if(cache[key]&&Date.now()-cache[key].time<ttl)return {...cache[key].data,cached:true};
 if(Date.now()<(retryAfter[key]??0))return fallback(key);
 if(pending[key])return pending[key];
 pending[key]=(async()=>{
  try{
   let data;
   if(key==='bonds')data=await loadEuroBonds();
   else{
    const previous=cache.curves?.data.curves??snapshots.curves;
    data={curves:await Promise.all(countryIds.map(async id=>{try{return await loadCurve(id)}catch{return {...previous.find(c=>c.id===id),fallback:true,error:'Aggiornamento non disponibile: rilevazione salvata.'}}}))};
   }
   await persist(key,data);return data;
  }catch{retryAfter[key]=Date.now()+5*60*1000;return fallback(key)}
  finally{delete pending[key]}
 })();
 return pending[key];
}
const types={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.svg':'image/svg+xml','.png':'image/png','.ico':'image/x-icon','.woff2':'font/woff2','.json':'application/json'};
const server=http.createServer(async(req,res)=>{
 const send=(status,data)=>{res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});res.end(JSON.stringify(data))};
 try{
  // Loopback only; reject foreign Host headers and browser origins for local control.
  if(![`127.0.0.1:${port}`,`localhost:${port}`].includes(req.headers.host??''))return send(403,{error:'Host non consentito'});
  const url=new URL(req.url,'http://127.0.0.1:'+port);
  if(url.pathname==='/_local/health'&&req.method==='GET')return send(200,{app:'bond-atlas-local',pid:process.pid,offline});
  if(url.pathname==='/_local/stop'&&req.method==='POST'){
   if(req.headers['x-bond-atlas-token']!==token||req.headers.origin)return send(403,{error:'Comando non autorizzato'});
   send(200,{stopped:true});setTimeout(shutdown,150);return;
  }
  if(req.method!=='GET'&&req.method!=='HEAD')return send(405,{error:'Metodo non consentito'});
  if(url.pathname==='/api/bonds')return send(200,await dataFor('bonds'));
  if(url.pathname==='/api/curves')return send(200,await dataFor('curves'));
  const relative=url.pathname==='/'?'index.html':decodeURIComponent(url.pathname).replace(/^\/+/, '');
  const filename=path.resolve(assets,relative);
  if(!filename.startsWith(assets+path.sep))return send(403,{error:'Percorso non consentito'});
  const contents=await readFile(filename);
  res.writeHead(200,{'Content-Type':types[path.extname(filename)]??'application/octet-stream','Cache-Control':filename.endsWith('.html')?'no-cache':'public, max-age=3600','X-Content-Type-Options':'nosniff'});res.end(req.method==='HEAD'?undefined:contents);
 }catch(e){send(e.code==='ENOENT'?404:500,{error:e.code==='ENOENT'?'Pagina non trovata':'Errore del servizio locale'})}
});
async function shutdown(){
 server.close();server.closeAllConnections();
 try{const state=await json(statePath);if(state.token===token)await unlink(statePath)}catch{}
 process.exit(0);
}
server.on('error',e=>{console.error(e.message);process.exit(1)});
server.listen(port,host,async()=>{
 await writeFile(statePath,JSON.stringify({pid:process.pid,port,token,startedAt:new Date().toISOString(),offline}));
 console.log(`Bond Atlas pronto su http://${host}:${port}${offline?' (offline)':''}`);
});
process.on('SIGINT',shutdown);process.on('SIGTERM',shutdown);
