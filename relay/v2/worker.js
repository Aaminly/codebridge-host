import { DurableObject } from 'cloudflare:workers';
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const HEX=/^[0-9a-f]{64}$/;
const reject=(status,message)=>new Response(message,{status});
async function hash(value){return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value))),b=>b.toString(16).padStart(2,'0')).join('')}
function route(req){
 const u=new URL(req.url);let m=u.pathname.match(/^\/v2\/hosts\/([^/]+)\/connect$/);
 if(m)return {hostId:m[1],role:'host'};
 m=u.pathname.match(/^\/v2\/hosts\/([^/]+)\/devices\/([^/]+)\/connect$/);
 if(m)return {hostId:m[1],deviceId:m[2],role:'device'};
 m=u.pathname.match(/^\/v2\/pairings\/([^/]+)\/(claim|resume)$/);
 if(m)return {hostId:u.searchParams.get('hostId'),pairingId:m[1],role:'pairing',resume:m[2]==='resume'};
 return null;
}
export default {async fetch(req,env){
 const r=route(req);
 if(!r||!UUID.test(r.hostId)||r.deviceId&&!UUID.test(r.deviceId)||r.pairingId&&!UUID.test(r.pairingId))return reject(404,'Unknown route');
 return env.HOSTS.getByName(r.hostId).fetch(req);
}};
export class HostPairing extends DurableObject{
 hostSocket(){return this.ctx.getWebSockets('host').find(s=>s.readyState===1)}
 phones(){return this.ctx.getWebSockets('phone').filter(s=>s.readyState===1)}
 async fetch(req){
  const r=route(req);if(!r||!UUID.test(r.hostId))return reject(404,'Unknown route');
  if(req.method!=='GET'||req.headers.get('Upgrade')?.toLowerCase()!=='websocket')return reject(426,'WebSocket required');
  const token=req.headers.get('Authorization')?.match(/^Bearer ([A-Za-z0-9_-]{43})$/)?.[1];
  if(!token)return reject(401,'Authentication required');
  const digest=await hash(token);let status=401;
  await this.ctx.storage.transaction(async tx=>{
   const existingId=await tx.get('hostId');if(existingId&&existingId!==r.hostId)return;
   if(r.role==='host'){
    const known=await tx.get('hostVerifier');if(known&&known!==digest)return;
    if(!known){await tx.put('hostId',r.hostId);await tx.put('hostVerifier',digest)}status=101;
   }else{
    if(!existingId)return;
    if(!this.hostSocket()){status=503;return}
    if(this.phones().length>=8){status=429;return}
    if(r.role==='device'){
     if(await tx.get('device:'+r.deviceId)===digest)status=101;
    }else{
     const key='pair:'+r.pairingId,p=await tx.get(key);if(!p)return;
     const minute=Math.floor(Date.now()/60000);if(p.minute!==minute){p.minute=minute;p.attempts=0}
     p.attempts++;await tx.put(key,p);if(p.attempts>10){status=429;return}
     if(p.expiresAt<=Date.now()||(!r.resume&&(p.used||p.capabilityHash!==digest))||(r.resume&&(!p.used||p.recoveryHash!==digest)))return;
     p.used=true;await tx.put(key,p);status=101;
    }
   }
  });
  if(status!==101)return reject(status,status===503?'Desktop offline':'Authentication or connection limit rejected');
  if(r.resume)for(const phone of this.phones())if(phone.deserializeAttachment().pairingId===r.pairingId)phone.close(1012,'Pairing resumed');
  if(r.role==='host'){
   for(const p of this.phones())p.close(1012,'Desktop reconnected');
   for(const s of this.ctx.getWebSockets('host'))s.close(1012,'Host replaced');
  }
  const pair=new WebSocketPair(),id=crypto.randomUUID(),a={...r,id};
  this.ctx.acceptWebSocket(pair[1],[r.role==='host'?'host':'phone',id]);pair[1].serializeAttachment(a);
  if(r.role!=='host')this.hostSocket().send(JSON.stringify({type:'open',id,role:r.role,resume:r.resume||false,pairingId:r.pairingId,deviceId:r.deviceId}));
  return new Response(null,{status:101,webSocket:pair[0]});
 }
 async webSocketMessage(ws,data){
  try{
   if(typeof data!=='string'||new TextEncoder().encode(data).length>1048576)throw Error('Frame exceeds limit');
   const a=ws.deserializeAttachment(),x=JSON.parse(data);
   if(a.role==='host'){
    if(ws!==this.hostSocket())throw Error('Host replaced');
    if(x.type==='offer'){
     if(!UUID.test(x.pairingId)||!HEX.test(x.capabilityHash)||!Number.isSafeInteger(x.expiresAt)||x.expiresAt>Date.now()+120000)throw Error('Invalid pairing');
     const pairs=await this.ctx.storage.list({prefix:'pair:'});
     for(const [k,p]of pairs)if(p.expiresAt<=Date.now())await this.ctx.storage.delete(k);
     if([...pairs.values()].filter(p=>p.expiresAt>Date.now()).length>=8)throw Error('Pairing limit');
     if(await this.ctx.storage.get('pair:'+x.pairingId))throw Error('Pairing already registered');
     await this.ctx.storage.put('pair:'+x.pairingId,{capabilityHash:x.capabilityHash,expiresAt:x.expiresAt,used:false,attempts:0});
     ws.send(JSON.stringify({type:'offered',pairingId:x.pairingId}));return;
    }
    if(x.type==='reject'){
     if(!UUID.test(x.pairingId))throw Error('Invalid pairing');await this.ctx.storage.delete('pair:'+x.pairingId);
     for(const p of this.phones())if(p.deserializeAttachment().pairingId===x.pairingId)p.close(1008,'Pairing rejected');return;
    }
    if(x.type==='recovery'){
     const phone=this.phones().find(p=>p.deserializeAttachment().id===x.id);
     if(!phone||phone.deserializeAttachment().role!=='pairing'||!HEX.test(x.credentialHash))throw Error('Invalid recovery');
     const key='pair:'+phone.deserializeAttachment().pairingId,p=await this.ctx.storage.get(key);
     if(!p||!p.used||p.expiresAt<=Date.now()||p.recoveryHash)throw Error('Recovery unavailable');
     p.recoveryHash=x.credentialHash;await this.ctx.storage.put(key,p);ws.send(JSON.stringify({type:'recoveryReady',id:x.id}));return;
    }
    if(x.type==='authorize'){
     if(!UUID.test(x.deviceId)||!HEX.test(x.credentialHash))throw Error('Invalid device');
     const phone=this.phones().find(p=>p.deserializeAttachment().id===x.id);
     if(!phone||phone.deserializeAttachment().role!=='pairing')throw Error('Pairing connection unavailable');
     const pending=await this.ctx.storage.get('pair:'+phone.deserializeAttachment().pairingId);
     if(!pending||!pending.used||pending.expiresAt<=Date.now())throw Error('Pairing expired');
     await this.ctx.storage.put('device:'+x.deviceId,x.credentialHash);
     phone.serializeAttachment({...phone.deserializeAttachment(),role:'device',deviceId:x.deviceId});
     ws.send(JSON.stringify({type:'authorized',id:x.id,deviceId:x.deviceId}));return;
    }
    if(x.type==='revoke'){
     if(!UUID.test(x.deviceId))throw Error('Invalid device');await this.ctx.storage.delete('device:'+x.deviceId);
     for(const p of this.phones())if(p.deserializeAttachment().deviceId===x.deviceId)p.close(1008,'Device revoked');
     ws.send(JSON.stringify({type:'revoked',deviceId:x.deviceId}));return;
    }
    const phone=this.phones().find(p=>p.deserializeAttachment().id===x.id);
    if(!phone){ws.send(JSON.stringify({type:'close',id:x.id}));return}
    if(x.type==='close'){phone.close(1013,'Desktop connection unavailable');return}
    if(x.type!=='data')throw Error('Unknown message');this.validateCiphertext(x.data);phone.send(JSON.stringify({type:'data',data:x.data}));
   }else{
    if(x.type!=='data')throw Error('Phone role cannot manage hosts or credentials');this.validateCiphertext(x.data);
    const host=this.hostSocket();if(!host){ws.close(1013,'Desktop offline');return}
    host.send(JSON.stringify({type:'data',id:a.id,data:x.data}));
   }
  }catch{ws.close(1008,'Invalid or oversized protocol message')}
 }
 validateCiphertext(value){if(typeof value!=='string'||value.length>87380||!value.length||! /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value))throw Error('Invalid ciphertext frame')}
 webSocketClose(ws,code=1000,reason=''){
  // Required before compatibility date 2026-04-07; harmless with automatic replies.
  if(ws.readyState!==3)ws.close([1004,1005,1006,1015].includes(code)?1001:code,reason);
  const a=ws.deserializeAttachment();if(a.role==='host'){
  if(!this.ctx.getWebSockets('host').some(s=>s!==ws&&s.readyState===1))for(const p of this.phones())p.close(1013,'Desktop offline');
 }else this.hostSocket()?.send(JSON.stringify({type:'close',id:a.id}))}
 webSocketError(ws){this.webSocketClose(ws)}
}
