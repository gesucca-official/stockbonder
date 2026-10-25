import {spawn} from 'node:child_process';
import {mkdir,readFile,open} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
const runtime=path.join(root,'.sites-runtime','local-app');
const url='http://127.0.0.1:8787';
const [action='start',...options]=process.argv.slice(2);
const offline=options.includes('--offline');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function health(){
 try{const r=await fetch(url+'/_local/health',{signal:AbortSignal.timeout(1500)});const d=await r.json().catch(()=>null);if(d?.app!=='bond-atlas-local')throw Error('Porta 8787 occupata da un altro servizio.');return d}
 catch(e){if(e.message==='Porta 8787 occupata da un altro servizio.')throw e;return null}
}
function openBrowser(){
 if(options.includes('--no-browser'))return;
 const child=spawn('powershell.exe',['-NoProfile','-NonInteractive','-Command',`Start-Process '${url}'`],{windowsHide:true,stdio:'ignore'});child.unref();
}
try{
 if(Number(process.versions.node.split('.')[0])<24)throw Error('Per questa versione locale serve Node.js 24 o successivo.');
 if(!['start','stop','status'].includes(action))throw Error('Comando non riconosciuto.');
 const running=await health();
 if(action==='status'){console.log(running?'Bond Atlas attivo: '+url:'Bond Atlas non avviato.');process.exit(0)}
 if(action==='stop'){
  if(!running){console.log('Bond Atlas e gia arrestato.');process.exit(0)}
  const state=JSON.parse(await readFile(path.join(runtime,'server.json'),'utf8'));
  if(state.pid!==running.pid)throw Error('Il servizio non corrisponde a questa installazione.');
  const r=await fetch(url+'/_local/stop',{method:'POST',headers:{'X-Bond-Atlas-Token':state.token},signal:AbortSignal.timeout(3000)});
  if(!r.ok)throw Error('Arresto non riuscito.');
  for(let i=0;i<30&&await health();i++)await sleep(200);
  if(await health())throw Error('Il servizio non si e arrestato.');
  console.log('Bond Atlas arrestato.');process.exit(0);
 }
 if(running){if(offline!==running.offline)throw Error('Bond Atlas e gia aperto in un’altra modalita. Arrestalo prima di riavviarlo.');openBrowser();console.log('Bond Atlas gia attivo: '+url);process.exit(0)}
 await readFile(path.join(root,'local-dist','index.html'));
 await mkdir(runtime,{recursive:true});
 const log=await open(path.join(runtime,'server.log'),'a');
 const child=spawn(process.execPath,[path.join(root,'scripts','local-server.mjs'),...(offline?['--offline']:[])],{cwd:root,detached:true,windowsHide:true,stdio:['ignore',log.fd,log.fd]});
 await new Promise((resolve,reject)=>{child.once('spawn',resolve);child.once('error',reject)});child.unref();await log.close();
 for(let i=0;i<60;i++){
  if(await health()){openBrowser();console.log('Bond Atlas pronto: '+url);process.exit(0)}
  await sleep(500);
 }
 throw Error('Avvio non riuscito. Consulta .sites-runtime/local-app/server.log.');
}catch(e){console.error('Bond Atlas: '+e.message);process.exitCode=1}
