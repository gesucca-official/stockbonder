"use client";
import {useCallback,useEffect,useMemo,useRef,useState} from "react";
import {flushSync} from "react-dom";
import {RefreshCw,ArrowUpRight,Info,Download} from "lucide-react";
import {ResponsiveContainer,LineChart,Line,XAxis,YAxis,CartesianGrid,Tooltip,ReferenceDot} from "recharts";
import {Slider} from "@/components/ui/slider";
import {Checkbox} from "@/components/ui/checkbox";
import {RadioGroup,RadioGroupItem} from "@/components/ui/radio-group";
import {Tabs,TabsList,TabsTrigger} from "@/components/ui/tabs";
import {Select,SelectTrigger,SelectValue,SelectContent,SelectItem} from "@/components/ui/select";
import {Table,TableBody,TableCell,TableHead,TableHeader,TableRow} from "@/components/ui/table";
import {analyze,metrics} from "@/lib/bond-model";
import type {Curve} from "@/lib/bond-model";
import snapshot from "@/lib/snapshot.json";

const fmt=(n:number,d=2)=>n.toLocaleString("it-IT",{minimumFractionDigits:d,maximumFractionDigits:d});
const date=(s:string)=>new Date(s+"T12:00:00Z").toLocaleDateString("it-IT",{day:"numeric",month:"short",year:"numeric"});
const signed=(n:number)=>(n>0?"+":"")+fmt(n)+"%";
export default function GlobalDashboard(){
 const [curves,setCurves]=useState<Curve[]>(snapshot);
 const [focus,setFocus]=useState("US"),[penalty,setPenalty]=useState(10),[cap,setCap]=useState(8),[shock,setShock]=useState(100);
 const [axis,setAxis]=useState("maturity"),[compare,setCompare]=useState(true),[loading,setLoading]=useState(false),[status,setStatus]=useState("Rilevazioni salvate · collegamento alle fonti in corso");
 const [today,setToday]=useState("");
 const current=curves.find(c=>c.id===focus)!;
 const result=useMemo(()=>analyze(current.points,penalty,cap,shock),[current,penalty,cap,shock]);
 const {rows,best}=result;
 const stateRef=useRef({curves,focus,penalty,cap,shock});stateRef.current={curves,focus,penalty,cap,shock};
 const refresh=useCallback(async()=>{
  setLoading(true);setStatus("Verifica delle cinque fonti ufficiali…");
  try{const r=await fetch("/api/curves");if(!r.ok)throw new Error();const data=await r.json() as {curves?:Curve[];cached?:boolean};if(!Array.isArray(data.curves)||data.curves.length!==5)throw new Error();setCurves(data.curves);const failed=data.curves.filter((c:Curve)=>c.fallback).length;setStatus(failed?failed+" fonti non raggiungibili · mantenute le rilevazioni precedenti":data.cached?"Fonti verificate di recente · cache di 15 minuti":"Acquisizione completata · consulta la data di ciascuna curva");}catch{setStatus("Collegamento non riuscito · mostro le rilevazioni salvate, con la loro data");setCurves(v=>v.map(c=>({...c,fallback:true})))}finally{setLoading(false)}
 },[]);
 useEffect(()=>{setToday(new Date().toISOString().slice(0,10));void refresh()},[refresh]);
 useEffect(()=>{
  type Tool={name:string;description:string;inputSchema:object;annotations:object;execute:(x:unknown)=>unknown};
  const context=(document as Document&{modelContext?:{registerTool:(t:Tool,o:{signal:AbortSignal})=>unknown}}).modelContext;
  if(!context?.registerTool)return;const lifetime=new AbortController();
  const read=()=>{const s=stateRef.current;const curve=s.curves.find(c=>c.id===s.focus)!;const a=analyze(curve.points,s.penalty,s.cap,s.shock);return {country:curve.name,currency:curve.currency,date:curve.date,penaltyBps:s.penalty,maxDuration:s.cap,shockBps:s.shock,best:a.best,model:"Annual coupon theoretical proxy; not an investment recommendation"}};
  const tools:Tool[]=[{name:"read_bond_analysis",description:"Read the current country's yield-duration analysis and assumptions.",inputSchema:{type:"object",properties:{},additionalProperties:false},annotations:{readOnlyHint:true,untrustedContentHint:true},execute:()=>read()},{name:"configure_bond_analysis",description:"Set the visible country and analytical preferences, and calculate its sweet spot.",inputSchema:{type:"object",properties:{country:{type:"string",enum:["US","DE","GB","JP","CA"]},penaltyBps:{type:"number",minimum:0,maximum:50},maxDuration:{type:"number",minimum:1,maximum:30},shockBps:{type:"number",enum:[25,50,100,200]}},additionalProperties:false},annotations:{readOnlyHint:false,untrustedContentHint:true},execute:(input:unknown)=>{if(!input||typeof input!=="object"||Array.isArray(input))throw new Error("Invalid object");const x=input as Record<string,unknown>;if(Object.keys(x).some(k=>!["country","penaltyBps","maxDuration","shockBps"].includes(k)))throw new Error("Unknown parameter");if(x.country!==undefined&&!stateRef.current.curves.some(c=>c.id===x.country))throw new Error("Invalid country");for(const [key,min,max] of [["penaltyBps",0,50],["maxDuration",1,30]] as const){if(x[key]!==undefined&&(typeof x[key]!=="number"||!Number.isFinite(x[key])||x[key]<min||x[key]>max))throw new Error("Invalid range")}if(x.shockBps!==undefined&&![25,50,100,200].includes(x.shockBps as number))throw new Error("Invalid shock");flushSync(()=>{if(x.country!==undefined)setFocus(x.country as string);if(x.penaltyBps!==undefined)setPenalty(x.penaltyBps as number);if(x.maxDuration!==undefined)setCap(x.maxDuration as number);if(x.shockBps!==undefined)setShock(x.shockBps as number)});return read()}}];
  for(const tool of tools){try{void Promise.resolve(context.registerTool(tool,{signal:lifetime.signal})).catch(()=>{})}catch{}}
  return ()=>lifetime.abort();
 },[]);
 const visible=compare?curves:[current];
 const chartData=useMemo(()=>{
  if(axis==="maturity"){const maturities=[...new Set(visible.flatMap(c=>c.points.map(p=>p.maturity)))].sort((a,b)=>a-b);return maturities.map(t=>{const row:Record<string,number>={x:t};for(const c of visible){const point=c.points.find(p=>p.maturity===t);if(point)row[c.id]=point.yield}return row})}
  return visible.flatMap(c=>c.points.map(p=>({x:metrics(p).duration,[c.id]:p.yield}))).sort((a,b)=>a.x-b.x);
 },[curves,focus,compare,axis]);
 const age=today?Math.round((Date.parse(today)-Date.parse(current.date))/86400000):0;
 const next=best?rows.find(p=>p.duration>best.duration+1e-8&&p.efficient):undefined;
 function exportCSV(){const lines=[["paese","valuta","data","scadenza_anni","rendimento_annuo_pct","tasso_fonte_pct","duration_stimata_anni","convessita","score_non_rendimento","prezzo_shock_positivo_pct","prezzo_shock_negativo_pct","sweet_spot","penalita_pb_anno","duration_massima","shock_pb"],...rows.map(p=>[current.name,current.currency,current.date,p.maturity,p.yield,p.nativeYield??"",p.duration,p.convexity,p.score,p.up,p.down,p.maturity===best?.maturity?"si":"no",penalty,cap,shock])];const csv="\uFEFF"+lines.map(r=>r.map(v=>'"'+String(v).replaceAll('"','""')+'"').join(";")).join("\r\n");const url=URL.createObjectURL(new Blob([csv],{type:"text/csv;charset=utf-8"}));const a=document.createElement("a");a.href=url;a.download="bond-atlas-"+current.id+"-"+current.date+".csv";a.click();setTimeout(()=>URL.revokeObjectURL(url),500)}
 return <main>
 <div className="workspace">
  <div className="heading"><div><p className="eyebrow">MERCATI GLOBALI / TITOLI DI STATO</p><h1>Quanto rende il tempo.</h1><p className="intro">Esplora le curve. Trova il tuo equilibrio tra rendimento e rischio di tasso.</p></div><button className="action" onClick={refresh} disabled={loading}><RefreshCw size={16} className={loading?"animate-spin":""}/>{loading?"Aggiornamento…":"Aggiorna dati"}</button></div>
  <RadioGroup aria-label="Paese da analizzare" value={focus} onValueChange={setFocus} className="marketbar !flex">
   {curves.map(c=><label key={c.id} className={"market "+(focus===c.id?"active":"")}><div className="market-title"><RadioGroupItem id={"market-"+c.id} value={c.id} aria-label={c.name}/><b>{c.name}</b></div><span>{c.currency} · {c.instrument}</span><span>{date(c.date)}{c.fallback?" · salvata":""}</span></label>)}
  </RadioGroup>
  <div className="status" role="status">{status}</div>
  {current.fallback&&<p className="error-box">La fonte di {current.name} non è stata aggiornata in questa verifica. Il calcolo usa i dati del {date(current.date)}.</p>}
  <div className="main-grid">
   <section className="chart-panel">
    <div className="panel-heading"><div><p className="eyebrow">LE CURVE SOVRANE</p><h2>{axis==="maturity"?"Rendimento per scadenza":"Rendimento per duration"}</h2></div><Tabs value={axis} onValueChange={setAxis}><TabsList aria-label="Asse orizzontale"><TabsTrigger value="maturity">Scadenza</TabsTrigger><TabsTrigger value="duration">Duration</TabsTrigger></TabsList></Tabs></div>
    <div className="legend">{visible.map(c=><span key={c.id}><i className="dot" style={{background:c.color}}/>{c.name} <span className="tiny">{c.currency} · {date(c.date)}</span></span>)}</div>
    <div className="chart-wrap" aria-label={"Curve dei rendimenti. Dati del mercato selezionato disponibili nella tabella sottostante."}>
     <ResponsiveContainer width="100%" height="100%"><LineChart data={chartData} margin={{top:20,right:25,left:0,bottom:24}} accessibilityLayer>
      <CartesianGrid vertical={false} stroke="#e2e8e0"/><XAxis type="number" dataKey="x" domain={[0,axis==="maturity"?30:"auto"]} tickLine={false} axisLine={false} tickFormatter={v=>fmt(Number(v),0)} label={{value:axis==="maturity"?"Scadenza residua (anni)":"Duration modificata stimata (anni)",position:"insideBottom",offset:-15,fontSize:13}}/>
      <YAxis domain={["auto","auto"]} tickFormatter={v=>fmt(Number(v),1)+"%"} tickLine={false} axisLine={false} width={63}/>
      <Tooltip contentStyle={{borderRadius:8,borderColor:"#cdd8cc",fontSize:14}} labelFormatter={v=>(axis==="maturity"?"Scadenza: ":"Duration: ")+fmt(Number(v),2)+" anni"} formatter={(v,name)=>[fmt(Number(v))+"%",String(name)]}/>
      {visible.map(c=><Line key={c.id} dataKey={c.id} name={c.name+" ("+c.currency+")"} stroke={c.color} strokeWidth={c.id===focus?3:1.7} strokeOpacity={c.id===focus?1:.55} dot={c.id===focus?{r:3,fill:c.color,strokeWidth:0}:false} connectNulls type="linear" isAnimationActive={false}/>)}
      {best&&<ReferenceDot x={axis==="maturity"?best.maturity:best.duration} y={best.yield} r={8} fill={current.color} stroke="#fff" strokeWidth={3} label={{value:"Sweet spot",position:"top",fill:current.color,fontSize:13}}/>}
     </LineChart></ResponsiveContainer>
    </div>
    <label className="check-label"><Checkbox checked={compare} onCheckedChange={v=>setCompare(v===true)}/>Confronta tutti i mercati</label>
    <div className="chart-note"><Info size={15} style={{display:"inline",marginRight:6}}/><b>Rendimenti lordi in valuta locale.</b> Le date delle rilevazioni sono diverse. Il confronto non comprende il cambio né il costo di una copertura valutaria. Le linee collegano i punti; il calcolo usa solo le scadenze in tabella.</div>
    <p className="note"><b>{current.name} · {date(current.date)}</b>{age>4?" · rilevazione di "+age+" giorni fa":""}<br/>{current.method}<br/><a className="source-link" href={current.sourceUrl} target="_blank" rel="noreferrer">{current.source} ↗</a></p>
   </section>
   <aside className="spot-panel">
    <p className="eyebrow">IL TUO COMPROMESSO / {current.currency}</p><h2>Sweet spot</h2>
    {best?<><div className="spot-number" aria-live="polite">{best.maturity}<small> anni di scadenza</small></div><div className="metrics"><div className="metric"><span>Rendimento lordo</span><strong>{fmt(best.yield)}%</strong></div><div className="metric"><span>Duration stimata</span><strong>{fmt(best.duration,1)} a</strong></div><div className="metric"><span>Prezzo con +{shock} pb</span><strong className="negative">{signed(best.up)}</strong></div></div></>:<p className="error-box">Nessuna scadenza rispetta il limite. Aumenta la duration massima.</p>}
    <label className="control-label" id="penalty-label"><span>Premio per anno di duration</span><b>{fmt(penalty,0)} pb</b></label><Slider ref={node=>{node?.querySelector('[role="slider"]')?.setAttribute('aria-labelledby','penalty-label')}} aria-labelledby="penalty-label" value={[penalty]} onValueChange={v=>setPenalty(v[0])} min={0} max={50} step={1}/><div className="control-footer"><span>Più rendimento</span><span>Più prudenza</span></div>
    <label className="control-label" id="cap-label"><span>Duration massima</span><b>{fmt(cap,1)} anni</b></label><Slider ref={node=>{node?.querySelector('[role="slider"]')?.setAttribute('aria-labelledby','cap-label')}} aria-labelledby="cap-label" value={[cap]} onValueChange={v=>setCap(v[0])} min={1} max={30} step={.5}/>
    <div className="control-label"><span>Scenario tassi</span><Select value={String(shock)} onValueChange={v=>setShock(Number(v))}><SelectTrigger aria-label="Variazione dei tassi"><SelectValue/></SelectTrigger><SelectContent>{[25,50,100,200].map(v=><SelectItem key={v} value={String(v)}>±{v} pb</SelectItem>)}</SelectContent></Select></div>
    <p className="result-explanation">Il punto massimizza <b>rendimento − {fmt(penalty/100,2)} × duration</b>, entro il limite scelto. Un punto base (pb) è 0,01 punti percentuali.</p>
    {best&&next&&<p className="tiny">La successiva scadenza efficiente, {next.maturity} anni, aggiunge {fmt((next.yield-best.yield)*100,0)} pb di rendimento e {fmt(next.duration-best.duration,1)} anni di duration.</p>}
    <p className="tiny">È un criterio di confronto regolabile. Il punteggio non è un rendimento atteso.</p>
   </aside>
  </div>
  <section className="table-panel"><div className="table-head"><div><p className="eyebrow">DENTRO LA CURVA / {current.name.toUpperCase()}</p><h2>Quanto rischio per quanto rendimento</h2></div><button className="action" onClick={exportCSV}><Download size={15}/>Esporta CSV</button></div>
   <Table><TableHeader><TableRow><TableHead>Scadenza</TableHead><TableHead>Rend. lordo annuo</TableHead><TableHead>Duration stimata</TableHead><TableHead>Prezzo con +{shock} pb</TableHead><TableHead>Prezzo con −{shock} pb</TableHead><TableHead>Valutazione</TableHead></TableRow></TableHeader><TableBody>{rows.map(p=><TableRow key={p.maturity} className={best?.maturity===p.maturity?"selected-row":""}><TableCell><b>{p.maturity} anni</b></TableCell><TableCell>{fmt(p.yield)}%</TableCell><TableCell>{fmt(p.duration)} anni</TableCell><TableCell className="negative">{signed(p.up)}</TableCell><TableCell className="positive">{signed(p.down)}</TableCell><TableCell>{p.maturity===best?.maturity?<span className="pill">↗ Sweet spot</span>:p.duration>cap?<span className="tiny">Oltre il limite</span>:p.efficient?"Efficiente":<span className="tiny">Dominata*</span>}</TableCell></TableRow>)}</TableBody></Table>
   <p className="note">* Una scadenza è dominata se ne esiste un'altra con rendimento almeno uguale e duration non superiore, con almeno un vantaggio. Gli shock mostrano la variazione immediata del prezzo del titolo teorico: non sono rendimenti totali a un anno.</p>
  </section>
  <details className="methodology" id="method"><summary>Come funziona · ipotesi, limiti e fonti</summary><div className="method-grid">
   <div><h3>Scadenza e duration rispondono a domande diverse</h3><p>La scadenza è il tempo al rimborso. La duration modificata stima la sensibilità del prezzo ai rendimenti di mercato. Per piccoli movimenti: variazione di prezzo ≈ −duration × variazione del rendimento.</p><h3>Un modello comune, dichiarato</h3><p>Per ogni punto costruiamo un'obbligazione teorica con rimborso a 100, cedole annuali e cedola uguale al rendimento annuo della curva. I flussi sono scontati al suo rendimento a scadenza. La duration è calcolata sui flussi, senza equipararla alla scadenza. Per rendimenti negativi usiamo cedola zero e prezzo sopra 100.</p><p>Per Treasury e JGB convertiamo i rendimenti semestrali in equivalenti annui: (1 + y/2)² − 1. Per UK e Canada ricaviamo il tasso alla pari dai fattori di sconto spot: c = (1 − DF finale) / somma dei DF annuali. La Germania fornisce già tassi alla pari annuali.</p></div>
   <div><h3>Lo sweet spot dipende dalle tue preferenze</h3><p>Scegliamo la scadenza con il maggiore punteggio y − λD tra i punti efficienti entro la duration massima. λ è il premio richiesto per anno di duration; 10 pb corrispondono a 0,10 punti percentuali. In caso di parità preferiamo la duration minore. Non viene stimata una scadenza intermedia fra i punti disponibili.</p><h3>Cosa è incluso negli scenari</h3><p>Ricalcoliamo il prezzo di tutti i flussi mantenendo fissa la cedola e variando il rendimento di ±25, 50, 100 o 200 pb. Il calcolo include la non linearità prezzo/rendimento, ma non il passare del tempo, il reinvestimento o il roll-down.</p><p>Le duration sono stime su titoli teorici, non dati dei singoli ISIN. Le curve restano diverse per metodo e data: i JGB sono benchmark, non una curva alla pari pura. Cambio, rischio di credito, liquidità, imposte e costi non entrano nel punteggio. Nessuna classifica di convenienza tra paesi.</p></div>
   </div><h3 className="sources-title">Fonti ufficiali e stato dei dati</h3><div className="source-list">{curves.map(c=><div className="source-card" key={c.id}><a href={c.sourceUrl} target="_blank" rel="noreferrer">{c.source} ↗</a><b>{date(c.date)} · {c.currency}</b><p>{c.frequency}<br/>{c.fallback?"Copia salvata, fonte non raggiunta":"Ultima acquisizione: "+new Date(c.retrievedAt).toLocaleString("it-IT",{timeZone:"Europe/Rome"})}</p></div>)}</div><p className="note">I dati sono richiesti all'apertura e con “Aggiorna dati”, con cache di 15 minuti. Se una fonte non risponde, resta visibile l'ultima rilevazione acquisita, segnalata come copia salvata. Le curve ufficiali restano disponibili per cinque mercati. La vista «Titoli in euro» aggiunge le curve osservate dei singoli titoli europei.</p>
  </details>
  <footer className="footer-note">BOND ATLAS · Strumento di analisi, non una raccomandazione di acquisto. Rendimento lordo annuo; analisi limitata al rischio di tasso.</footer>
 </div></main>
}


