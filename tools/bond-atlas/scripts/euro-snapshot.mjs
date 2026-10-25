import {writeFile} from 'node:fs/promises';
import {loadEuroBonds} from '../lib/euro-source.ts';
const data=await loadEuroBonds();
await writeFile(new URL('../lib/euro-snapshot.json',import.meta.url),JSON.stringify(data));
console.log(`Saved ${data.bonds.length} EUR bonds as of ${data.asOf}.`);
