import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import tailwind from '@tailwindcss/postcss';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('./',import.meta.url));
export default defineConfig({
 root:root+'local',
 publicDir:root+'public',
 plugins:[react()],
 resolve:{alias:{'@':root}},
 css:{postcss:{plugins:[tailwind()]}},
 build:{outDir:root+'local-dist',emptyOutDir:true},
});
