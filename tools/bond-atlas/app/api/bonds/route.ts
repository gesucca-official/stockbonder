import {loadEuroBonds} from '@/lib/euro-source';
import snapshot from '@/lib/euro-snapshot.json';
import type {EuroDataset} from '@/lib/euro-bonds';
let cache:{time:number;data:EuroDataset}|undefined;
let pending:Promise<EuroDataset>|undefined;
let retryAfter=0;
export async function GET(){
 if(cache&&Date.now()-cache.time<6*60*60*1000)return Response.json({...cache.data,cached:true});
 if(Date.now()<retryAfter)return Response.json({...cache?.data??snapshot,fallback:true});
 pending??=loadEuroBonds();
 try{const data=await pending;cache={time:Date.now(),data};retryAfter=0;return Response.json(data)}
 catch{retryAfter=Date.now()+5*60*1000;return Response.json({...cache?.data??snapshot,fallback:true})}
 finally{pending=undefined}
}
