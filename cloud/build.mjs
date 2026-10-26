// Build a single Worker module that can be uploaded through the Cloudflare API.
import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';
const logic=readFileSync(new URL('./logic.mjs',import.meta.url),'utf8').replace(/^export /gm,'');
const worker=readFileSync(new URL('./worker.mjs',import.meta.url),'utf8').replace(/^import .* from '\.\/logic\.mjs';\r?\n/m,'');
const html=readFileSync(new URL('../retailpilot/static/index.html',import.meta.url),'utf8');
const bundle=logic+'\n'+worker.replace("'__DASHBOARD_HTML__'",JSON.stringify(html));
mkdirSync(new URL('./dist/',import.meta.url),{recursive:true});
writeFileSync(new URL('./dist/worker.mjs',import.meta.url),bundle);
console.log('Cloudflare Worker bundle generated');
