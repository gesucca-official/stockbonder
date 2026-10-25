import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {price,metrics,analyze,spotToPar,annualEquivalent} from '../lib/bond-model.ts';
import {parseCSV,parseUS,parseDE,parseJP,parseCA,parseGB} from '../lib/sources.ts';
const close=(a,b,tol=1e-9)=>assert.ok(Math.abs(a-b)<tol,`${a} != ${b}`);
// Independently known valuations and sensitivities.
close(price(1,.05,.05),1);
close(price(2,.05,0),1.10);
close(price(10,0,.05),1/1.05**10);
close(metrics({maturity:10,yield:0}).duration,10);
close(metrics({maturity:1,yield:5}).duration,1/1.05);
const bond={maturity:10,yield:5};const h=1e-5;
const numerical=(price(10,.05,.05-h)-price(10,.05,.05+h))/(2*h);
close(metrics(bond).duration,numerical,2e-7);
close(metrics({maturity:5,yield:-1}).duration,5/.99);
close(annualEquivalent(4),4.04);
// A flat continuously compounded zero curve yields a flat annual par curve.
const flat=spotToPar(Array.from({length:30},(_,i)=>({maturity:i+1,yield:3})));
flat.forEach(p=>close(p.yield,(Math.exp(.03)-1)*100));
assert.equal(spotToPar([{maturity:1,yield:3},{maturity:3,yield:4}]).length,1);
const rising=[{maturity:1,yield:3},{maturity:5,yield:4},{maturity:10,yield:5}];
assert.equal(analyze(rising,0,30,100).best.maturity,10);
assert.equal(analyze(rising,50,30,100).best.maturity,1);
assert.equal(analyze(rising,0,1,100).best.maturity,1);
assert.equal(analyze(rising,0,.5,100).best,null);
const inv=analyze([{maturity:1,yield:5},{maturity:10,yield:3}],0,30,100);
assert.equal(inv.best.maturity,1);assert.equal(inv.rows[1].efficient,false);
const stressed=analyze([bond],10,30,100).rows[0];assert.ok(stressed.up<0&&stressed.down>0&&stressed.down>-stressed.up);
assert.throws(()=>analyze(rising,NaN,3,100));assert.throws(()=>price(5,.05,-1));
assert.deepEqual(parseCSV('a,"b,c",d\n1,"a""b",3'),[['a','b,c','d'],['1','a"b','3']]);
const now=new Date('2026-10-07T12:00:00Z');
const xml='<feed><entry><d:NEW_DATE>2026-10-06T00:00:00</d:NEW_DATE><d:BC_1YEAR>4</d:BC_1YEAR><d:BC_2YEAR m:null="true"/><d:BC_3YEAR>5</d:BC_3YEAR><d:BC_5YEAR>6</d:BC_5YEAR><d:BC_30YEARDISPLAY>9</d:BC_30YEARDISPLAY></entry></feed>';
const us=parseUS(xml,now);assert.equal(us.points.length,3);assert.ok(!us.points.some(p=>p.maturity===2||p.maturity===30));
assert.throws(()=>parseUS('<html>Error</html>',now));assert.throws(()=>parseCA('Date,ZC100YR\n2026-10-06,na',now));
const curves=JSON.parse(await readFile(new URL('../lib/snapshot.json',import.meta.url),'utf8'));
assert.equal(curves.length,5);
for(const c of curves){assert.ok(c.points.length>=3);assert.ok(c.date<=now.toISOString().slice(0,10));let previous=Infinity;for(const p of [0,5,10,20,30,50]){const r=analyze(c.points,p,30,100);assert.ok(r.best);assert.ok(r.best.duration<=previous+1e-9);previous=r.best.duration;assert.ok(r.rows.every(x=>Number.isFinite(x.duration)&&Number.isFinite(x.up)&&x.up<0&&x.down>0))}}
// Actual provider fixture checks: gaps and non-observation rows are excluded.
const de=parseDE(await readFile('tests/fixtures/de.csv','utf8'),now);assert.equal(de.date,'2026-10-06');close(de.points[0].yield,2.93);
const gb=parseGB(new Uint8Array(await readFile('tests/fixtures/uk.zip')),now);assert.equal(gb.date,'2026-10-05');assert.equal(gb.points.length,30);
const ca=parseCA(await readFile('tests/fixtures/ca.csv','utf8'),now);assert.equal(ca.date,'2026-09-16');close(ca.points[0].yield,(Math.exp(.0294786)-1)*100);
const jp=parseJP('Date,1Y,2Y,3Y\n2026/10/6,1.652,1.93,2.077',now);close(jp.points[0].yield,annualEquivalent(1.652));
console.log('PASS: known prices, analytical duration, finite differences, negative and zero rates, spot-to-par conversion, constraints, dominance, monotonic preferences, stress repricing, CSV/XML/XLSX parsers and five real snapshots.');

