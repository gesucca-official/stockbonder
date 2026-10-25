export type Point = { maturity: number; yield: number; nativeYield?: number };
export type Curve = { id:string; name:string; currency:string; instrument:string; color:string; date:string; source:string; sourceUrl:string; method:string; frequency:string; points:Point[]; retrievedAt:string; error?:string; fallback?:boolean };
export type ModelPoint = Point & { duration:number; convexity:number; score:number; up:number; down:number; efficient:boolean };

// Annual-coupon par proxy. Yield and coupon inputs are decimal rates.
// Sensitivities refer to shifts in the effective annual yield, not a policy rate.
export function price(maturity:number,coupon:number,yieldRate:number){
 if(!Number.isInteger(maturity)||maturity<1||maturity>60||!Number.isFinite(coupon)||!Number.isFinite(yieldRate)||yieldRate<=-1) throw new Error('Parametri obbligazionari non validi');
 let p=0;for(let t=1;t<=maturity;t++)p+=(coupon+(t===maturity?1:0))/Math.pow(1+yieldRate,t);return p;
}
export function metrics(point:Point){
 const y=point.yield/100;const coupon=Math.max(y,0);const p=price(point.maturity,coupon,y);let duration=0,convexity=0;
 for(let t=1;t<=point.maturity;t++){const pv=(coupon+(t===point.maturity?1:0))/Math.pow(1+y,t);duration+=t*pv/(1+y);convexity+=t*(t+1)*pv/Math.pow(1+y,2)}
 return {duration:duration/p,convexity:convexity/p,coupon,price:p};
}
export function analyze(points:Point[],penaltyBps:number,maxDuration:number,shockBps:number){
 if(!Number.isFinite(penaltyBps)||penaltyBps<0||penaltyBps>50||!Number.isFinite(maxDuration)||maxDuration<.5||maxDuration>40||!Number.isFinite(shockBps)||shockBps<0||shockBps>200)throw new Error('Preferenze fuori intervallo');
 const rows:ModelPoint[]=points.filter(p=>Number.isInteger(p.maturity)&&p.maturity>=1&&p.maturity<=30&&Number.isFinite(p.yield)).map(p=>{const m=metrics(p);const shock=shockBps/10000;return {...p,duration:m.duration,convexity:m.convexity,score:p.yield-penaltyBps/100*m.duration,up:100*(price(p.maturity,m.coupon,p.yield/100+shock)/m.price-1),down:100*(price(p.maturity,m.coupon,p.yield/100-shock)/m.price-1),efficient:true}}).sort((a,b)=>a.maturity-b.maturity);
 for(const p of rows)p.efficient=!rows.some(q=>q.duration<=p.duration&&q.yield>=p.yield&&(q.duration<p.duration||q.yield>p.yield));
 const eligible=rows.filter(p=>p.duration<=maxDuration&&p.efficient);
 const best=eligible.toSorted((a,b)=>Math.abs(b.score-a.score)<1e-10?a.duration-b.duration:b.score-a.score)[0]??null;
 return {rows,best};
}
export function annualEquivalent(nominalPct:number,frequency=2){return 100*(Math.pow(1+nominalPct/100/frequency,frequency)-1)}
// Only derive par rates where all annual discount factors are available.
export function spotToPar(points:Point[]):Point[]{
 const map=new Map(points.map(p=>[p.maturity,p.yield]));const result:Point[]=[];let sum=0;
 for(let t=1;t<=30;t++){const z=map.get(t);if(z===undefined||!Number.isFinite(z))break;const d=Math.exp(-z/100*t);sum+=d;result.push({maturity:t,yield:100*(1-d)/sum,nativeYield:z})}return result;
}
