import {loadCurve,countryIds} from '../lib/sources.ts';
import {writeFile} from 'node:fs/promises';
const curves=await Promise.all(countryIds.map(id=>loadCurve(id)));
await writeFile(new URL('../lib/snapshot.json',import.meta.url),JSON.stringify(curves,null,2));
console.log(curves.map(c=>({id:c.id,date:c.date,points:c.points.length,first:c.points[0],last:c.points.at(-1)})));
