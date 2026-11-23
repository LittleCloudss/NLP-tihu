import {copyFile,mkdir,readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
const items=['build/three.module.js','build/three.core.js','examples/jsm/controls/OrbitControls.js','LICENSE'];
await mkdir('web/vendor/addons/controls',{recursive:true});
const hashes={version:JSON.parse(await readFile('node_modules/three/package.json','utf8')).version,files:{}};
for(const src of items){const dst=src.startsWith('build/')?src.slice(6):src.startsWith('examples/jsm/')?'addons/'+src.slice(13):src;await copyFile('node_modules/three/'+src,'web/vendor/'+dst);hashes.files[dst]=createHash('sha256').update(await readFile('web/vendor/'+dst)).digest('hex');}
await writeFile('web/vendor/manifest.json',JSON.stringify(hashes,null,2));
console.log('Vendored Three.js '+hashes.version+' for offline use.');
