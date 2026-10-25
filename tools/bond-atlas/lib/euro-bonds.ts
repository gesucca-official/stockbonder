export const EURO_COUNTRIES = [
 ['AT','Austria','#b07c45'],['BE','Belgio','#886b9a'],['BG','Bulgaria','#59805c'],
 ['CY','Cipro','#b09247'],['HR','Croazia','#a56272'],['EE','Estonia','#54889f'],
 ['FI','Finlandia','#506cb2'],['FR','Francia','#527eab'],['DE','Germania','#615e50'],
 ['GR','Grecia','#338a99'],['IE','Irlanda','#7c9647'],['IT','Italia','#16715b'],
 ['LV','Lettonia','#9f5469'],['LT','Lituania','#8d8548'],['NL','Paesi Bassi','#ca8243'],
 ['PL','Polonia','#ba6c76'],['PT','Portogallo','#718442'],['RO','Romania','#8276a4'],
 ['SI','Slovenia','#4c8a7c'],['ES','Spagna','#b47643'],['HU','Ungheria','#7c6b65'],
] as const;
export const EURO_SOURCE = 'https://www.simpletoolsforinvestors.eu/documentivari.php';
export const EURO_MONITOR = 'https://www.simpletoolsforinvestors.eu/monitor_info.php?monitor=europa&yieldtype=G&timescale=DUR';
export type EuroBond = {
 isin:string; country:string; name:string; currency:'EUR'; maturity:string; coupon:number;
 yield:number; duration:number; price:number; priceType:'LP'|'RP'; date:string;
 lot:number; volume:number; volumeRating:number; detailUrl:string;
};
export type EuroDataset = {asOf:string;retrievedAt:string;source:string;bonds:EuroBond[];excluded:number;fallback?:boolean};
export type BondPreferences = {penalty:number;cap:number;minYears:number;maxLot:number;minVolume:number;maxAge:number};
export const DEFAULT_PREFERENCES:BondPreferences={penalty:10,cap:8,minYears:.5,maxLot:1000,minVolume:10000,maxAge:4};
export type RankedBond=EuroBond&{years:number;age:number;score:number;eligible:boolean;reasons:string[];efficient:boolean};
export const daysBetween=(a:string,b:string)=>(Date.parse(a+'T12:00:00Z')-Date.parse(b+'T12:00:00Z'))/86400000;
export function rankBonds(bonds:EuroBond[],country:string,p:BondPreferences,today:string){
 if(!Number.isFinite(Date.parse(today))||Object.values(p).some(v=>!Number.isFinite(v))||p.penalty<0||p.cap<=0||p.minYears<0||p.maxLot<=0||p.minVolume<0||p.maxAge<0)throw new Error('Parametri non validi');
 const rows:RankedBond[]=bonds.filter(b=>b.country===country).map(b=>{
  const years=daysBetween(b.maturity,today)/365.25,age=daysBetween(today,b.date),reasons:string[]=[];
  if(age<0||age>p.maxAge)reasons.push('Dati non recenti');
  if(b.priceType!=='LP'||b.volume<=0)reasons.push('Nessuno scambio nella rilevazione');
  if(b.volume>0&&b.volume<p.minVolume)reasons.push('Volume sotto soglia');
  if(b.lot>p.maxLot)reasons.push('Lotto oltre il limite');
  if(b.duration>p.cap)reasons.push('Duration oltre il limite');
  if(years<p.minYears||years<=0)reasons.push('Scadenza troppo vicina');
  if(![b.yield,b.duration,b.price,b.volume,b.lot,age,years].every(Number.isFinite)||b.duration<=0||b.price<=0||b.lot<=0)reasons.push('Dati incompleti');
  return {...b,years,age,score:b.yield-p.penalty/100*b.duration,eligible:reasons.length===0,reasons,efficient:false};
 });
 const eligible=rows.filter(r=>r.eligible);
 for(const r of eligible)r.efficient=!eligible.some(o=>o.duration<=r.duration&&o.yield>=r.yield&&(o.duration<r.duration||o.yield>r.yield));
 eligible.sort((a,b)=>b.score-a.score||a.duration-b.duration||b.volume-a.volume||a.isin.localeCompare(b.isin));
 rows.sort((a,b)=>Number(b.eligible)-Number(a.eligible)||b.score-a.score||a.isin.localeCompare(b.isin));
 return {rows,eligible,best:eligible[0]??null};
}
// First order price sensitivity, in percent, not a holding-period return.
export function priceShock(duration:number,shockBps:number){return -duration*shockBps/100}
