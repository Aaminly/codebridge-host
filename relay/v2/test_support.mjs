import fs from 'node:fs';import {webcrypto} from 'node:crypto';

export async function hash(s){return Buffer.from(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(s))).toString('hex')}
export function request(path,token){return new Request('http://local'+path,{headers:{Authorization:'Bearer '+token,Upgrade:'websocket'}})}
export async function fixture(){
 let source=fs.readFileSync(new URL('worker.js',import.meta.url),'utf8').replace("import { DurableObject } from 'cloudflare:workers';",'class DurableObject {constructor(ctx){this.ctx=ctx}}');
 const NativeResponse=globalThis.Response;
 globalThis.Response=class extends NativeResponse{constructor(body,opts){if(opts?.status===101){super(null);Object.defineProperty(this,'status',{value:101});this.webSocket=opts.webSocket}else super(body,opts)}};
 const sockets=[],data=new Map();let serial=Promise.resolve();
 const storage={get:async k=>data.get(k),put:async(k,v)=>data.set(k,v),delete:async k=>data.delete(k),list:async opts=>new Map([...data].filter(([k])=>k.startsWith(opts?.prefix||''))),transaction:fn=>{let p=serial.then(()=>fn(storage));serial=p.catch(()=>{});return p}};
 const ctx={storage,getWebSockets:tag=>sockets.filter(s=>!tag||s.tags.includes(tag)),acceptWebSocket:(s,tags)=>{s.tags=tags;sockets.push(s)}};
 globalThis.WebSocketPair=class{constructor(){const make=()=>({readyState:1,sent:[],send(v){this.sent.push(v)},close(){this.readyState=3},serializeAttachment(a){this.a=structuredClone(a)},deserializeAttachment(){return structuredClone(this.a)}});this[0]=make();this[1]=make()}};
 const {HostPairing}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
 return {relay:new HostPairing(ctx,{}),sockets,ctx};
}
