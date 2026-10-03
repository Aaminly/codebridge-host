import assert from 'node:assert/strict';import {test} from 'node:test';import {fixture,request,hash} from './test_support.mjs';
test('two hosts isolate credentials, role controls, revoke, and stale-close events',async()=>{
 const a=await fixture(),b=await fixture(),aId=crypto.randomUUID(),bId=crypto.randomUUID(),token='a'.repeat(43),other='b'.repeat(43);
 await a.relay.fetch(request(`/v2/hosts/${aId}/connect`,token));await b.relay.fetch(request(`/v2/hosts/${bId}/connect`,other));
 const host=a.sockets[0],pair=crypto.randomUUID(),cap='c'.repeat(43),device=crypto.randomUUID(),credential='d'.repeat(43);
 await a.relay.webSocketMessage(host,JSON.stringify({type:'offer',pairingId:pair,capabilityHash:await hash(cap),expiresAt:Date.now()+120000}));
 await a.relay.fetch(request(`/v2/pairings/${pair}/claim?hostId=${aId}`,cap));const phone=a.sockets[1];
 await a.relay.webSocketMessage(host,JSON.stringify({type:'authorize',id:phone.a.id,deviceId:device,credentialHash:await hash(credential)}));
 assert.equal((await b.relay.fetch(request(`/v2/hosts/${bId}/devices/${device}/connect`,credential))).status,401);
 await a.relay.webSocketMessage(phone,JSON.stringify({type:'data',data:'YWJj'}));assert.equal(JSON.parse(host.sent.at(-1)).data,'YWJj');assert.equal(b.sockets[0].sent.length,0);
 const stale=host;await a.relay.fetch(request(`/v2/hosts/${aId}/connect`,token));
 await a.relay.fetch(request(`/v2/hosts/${aId}/devices/${device}/connect`,credential));const active=a.sockets.at(-1);
 a.relay.webSocketClose(stale);assert.equal(active.readyState,1);
 await a.relay.webSocketMessage(a.sockets[2],JSON.stringify({type:'revoke',deviceId:device}));assert.equal(active.readyState,3);
 assert.equal((await a.relay.fetch(request(`/v2/hosts/${aId}/devices/${device}/connect`,credential))).status,401);
});
test('phone cannot replace host or mutate authorization; invalid and oversized frames close',async()=>{
 const f=await fixture(),id=crypto.randomUUID(),cap='c'.repeat(43),pair=crypto.randomUUID();await f.relay.fetch(request(`/v2/hosts/${id}/connect`,'a'.repeat(43)));
 const host=f.sockets[0];await f.relay.webSocketMessage(host,JSON.stringify({type:'offer',pairingId:pair,capabilityHash:await hash(cap),expiresAt:Date.now()+120000}));await f.relay.fetch(request(`/v2/pairings/${pair}/claim?hostId=${id}`,cap));
 await f.relay.webSocketMessage(f.sockets[1],JSON.stringify({type:'revoke',deviceId:crypto.randomUUID()}));assert.equal(f.sockets[1].readyState,3);assert.equal(host.readyState,1);
 await f.relay.webSocketMessage(host,'x'.repeat(1048577));assert.equal(host.readyState,3);
});
test('close callback reciprocates the handshake on older runtimes',async()=>{
 const f=await fixture();await f.relay.fetch(request(`/v2/hosts/${crypto.randomUUID()}/connect`,'a'.repeat(43)));const ws=f.sockets[0];ws.readyState=2;
 f.relay.webSocketClose(ws,1000,'Closed',true);assert.equal(ws.readyState,3);
});
test('concurrent reconnects cannot exceed eight phone connections',async()=>{
 const f=await fixture(),id=crypto.randomUUID(),pair=crypto.randomUUID(),device=crypto.randomUUID(),cap='c'.repeat(43),credential='d'.repeat(43);await f.relay.fetch(request(`/v2/hosts/${id}/connect`,'a'.repeat(43)));const host=f.sockets[0];
 await f.relay.webSocketMessage(host,JSON.stringify({type:'offer',pairingId:pair,capabilityHash:await hash(cap),expiresAt:Date.now()+120000}));await f.relay.fetch(request(`/v2/pairings/${pair}/claim?hostId=${id}`,cap));const phone=f.sockets[1];
 await f.relay.webSocketMessage(host,JSON.stringify({type:'authorize',id:phone.a.id,deviceId:device,credentialHash:await hash(credential)}));phone.close();
 const results=await Promise.all(Array.from({length:12},()=>f.relay.fetch(request(`/v2/hosts/${id}/devices/${device}/connect`,credential))));assert.equal(results.filter(r=>r.status===101).length,8);assert.equal(results.filter(r=>r.status===429).length,4);
});
