import {loadCurve,countryIds} from '@/lib/sources';
import snapshot from '@/lib/snapshot.json';
import type {Curve} from '@/lib/bond-model';
let cached:{time:number;curves:Curve[]}|undefined;
let pending:Promise<Curve[]>|undefined;
export async function GET(){
 if(cached&&Date.now()-cached.time<15*60*1000)return Response.json({curves:cached.curves,cached:true});
 pending??=Promise.all(countryIds.map(async id=>{try{return await loadCurve(id)}catch{const fallback=(cached?.curves??snapshot).find(c=>c.id===id);if(!fallback)throw new Error('Dati non disponibili');return {...fallback,fallback:true,error:'Aggiornamento non riuscito: ultima rilevazione disponibile.'}}}));
 try{const curves=await pending;cached={time:Date.now(),curves};return Response.json({curves,cached:false})}catch{return Response.json({error:'Dati temporaneamente non disponibili'},{status:503})}finally{pending=undefined}
}
