import {EURO_COUNTRIES,EURO_MONITOR,EURO_SOURCE} from './euro-bonds.ts';
import type {EuroBond,EuroDataset} from './euro-bonds.ts';

export function semicolonCSV(text:string):Record<string,string>[] {
 const rows:string[][]=[];let row:string[]=[],field='',quoted=false;
 for(let i=0;i<text.length;i++){const c=text[i];if(c==='"'){if(quoted&&text[i+1]==='"'){field+='"';i++}else quoted=!quoted}
 else if(!quoted&&(c===';'||c==='\n')){row.push(field.trim());field='';if(c==='\n'){rows.push(row);row=[]}}
 else if(c!=='\r')field+=c;}
 if(quoted)throw new Error('CSV incompleto');
 if(field||row.length){row.push(field.trim());rows.push(row)}
 const headers=rows.shift()?.map(s=>s.replace(/^\uFEFF/,''))??[];
 return rows.filter(r=>r.some(Boolean)).map(r=>Object.fromEntries(headers.map((key,i)=>[key,r[i]??''])));
}
const number=(s:string)=>s&&/^-?\d+(?:[.,]\d+)?$/.test(s)?Number(s.replace(',','.')):NaN;
const text=(s:string)=>s.replace(/<[^>]*>/g,'').replace(/&amp;/g,'&').replace(/&#39;|&apos;/g,"'").replace(/&nbsp;/g,' ').trim();
export function isoDate(s:string){const m=/^(\d{2})\/(\d{2})\/(\d{4})$/.exec(s);if(!m)return '';const iso=`${m[3]}-${m[2]}-${m[1]}`;return new Date(iso+'T12:00:00Z').toISOString().slice(0,10)===iso?iso:''}
export function parseEuroData(csv:string,monitor:string,now=new Date()):EuroDataset {
 const records=semicolonCSV(csv);
 if(!records[0]||!['isincode','grossytm','grossduration','pricetype','referencedate'].every(k=>k in records[0]))throw new Error('Schema della fonte cambiato');
 const meta=new Map<string,{type:string;detailUrl:string;name:string}>();
 for(const tr of monitor.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)){
  const cells=[...tr[1].matchAll(/<td\b[^>]*>([\s\S]*?)<\/td>/gi)].map(c=>c[1]);
  if(cells.length<16||text(cells[4])!=='EUR')continue;
  const isin=text(cells[0]);if(!/^[A-Z]{2}[A-Z0-9]{9}\d$/.test(isin))continue;
  const detail=cells[1].match(/href=['"](details\.php\?bondid=\d+&(?:amp;)?marketcode=[A-Z0-9]+)['"]/i)?.[1];
  meta.set(isin,{type:text(cells[12]),name:text(cells[3]),detailUrl:detail?new URL(detail.replaceAll('&amp;','&'),EURO_SOURCE).href:EURO_MONITOR});
 }
 if(meta.size<50)throw new Error('Anagrafiche insufficienti');
 const countries=new Set<string>(EURO_COUNTRIES.map(c=>'GOV_'+c[0]));
 const bonds:EuroBond[]=[];let excluded=0;
 for(const r of records){
  if(r.currencycode!=='EUR'||!countries.has(r.issuercode))continue;
  const m=meta.get(r.isincode);
  // Use the source's calculation type as a positive allowlist, plus exclude stepped/optional cashflows.
  if(!m||m.type!=='Fisso'||/STEP|FUTURA|VALORE|PI[UÙ]'?|CALL|INDICIZZ|INFLATION|AMMORT/i.test(m.name+' '+r.description)||r.status!=='Senior'){excluded++;continue}
  const maturity=isoDate(r.redemptiondate),date=isoDate(r.referencedate);
  const y=number(r.grossytm),duration=number(r.grossduration),price=number(r.price),coupon=number(r.currentcouponrate)*100,lot=number(r.minimumlot),volume=number(r.volume),volumeRating=number(r.volumevalue);
  if(!maturity||!date||![y,duration,price,coupon,lot,volume,volumeRating].every(Number.isFinite)||duration<=0||price<=0||lot<=0||volume<0||!['LP','RP'].includes(r.pricetype)||date>now.toISOString().slice(0,10)){excluded++;continue}
  bonds.push({isin:r.isincode,country:r.issuercode.slice(4),name:r.description.trim(),currency:'EUR',maturity,coupon,yield:y,duration,price,priceType:r.pricetype as 'LP'|'RP',date,lot,volume,volumeRating,detailUrl:m.detailUrl});
 }
 if(bonds.length<50||new Set(bonds.map(b=>b.country)).size<10||new Set(bonds.map(b=>b.isin)).size!==bonds.length)throw new Error('Copertura inattesa della fonte');
 const asOf=bonds.map(b=>b.date).sort().at(-1)!;
 return {asOf,retrievedAt:now.toISOString(),source:EURO_SOURCE,bonds,excluded};
}
async function fetchText(url:string){
 const r=await fetch(url,{signal:AbortSignal.timeout(20000),headers:{Accept:'text/html,text/csv;q=0.9'}});
 if(!r.ok)throw new Error('Fonte non disponibile');return r.text();
}
export async function loadEuroBonds(now=new Date()){
 const docs=await fetchText(EURO_SOURCE);
 // Discover the provider's current public export link; its filename may rotate.
 const path=docs.match(/href=['"](\.\/data\/export\/[A-Za-z0-9]+\.csv)['"][^>]*>\s*Dati End of Day\s*<\/a>/i)?.[1];
 if(!path)throw new Error('Archivio giornaliero non trovato');
 const [csv,monitor]=await Promise.all([fetchText(new URL(path,EURO_SOURCE).href),fetchText(EURO_MONITOR)]);
 return parseEuroData(csv,monitor,now);
}
