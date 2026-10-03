import assert from 'node:assert/strict';import {test} from 'node:test';
import {fixture,request,hash} from './test_support.mjs';
test('host bootstrap pins credential; offers expire and claims are one-use',async()=>{
 const f=await fixture();const token='a'.repeat(43),id=crypto.randomUUID();
 assert.equal((await f.relay.fetch(request(`/v2/hosts/${id}/connect`,token))).status,101);
 assert.equal((await f.relay.fetch(request(`/v2/hosts/${id}/connect`,'b'.repeat(43)))).status,401);
 const host=f.sockets[0],pair=crypto.randomUUID(),cap='c'.repeat(43);
 await f.relay.webSocketMessage(host,JSON.stringify({type:'offer',pairingId:pair,capabilityHash:await hash(cap),expiresAt:Date.now()+120000}));
 const url=`/v2/pairings/${pair}/claim?hostId=${id}`;
 const results=await Promise.all([f.relay.fetch(request(url,cap)),f.relay.fetch(request(url,cap))]);
 assert.deepEqual(results.map(r=>r.status).sort(),[101,401]);
 const expired=crypto.randomUUID();await f.relay.webSocketMessage(host,JSON.stringify({type:'offer',pairingId:expired,capabilityHash:await hash(cap),expiresAt:Date.now()-1}));
 assert.equal((await f.relay.fetch(request(`/v2/pairings/${expired}/claim?hostId=${id}`,cap))).status,401);
});
test('resume uses a distinct capability and cannot claim a second identity',async()=>{
 const f=await fixture(),id=crypto.randomUUID(),pair=crypto.randomUUID(),cap='c'.repeat(43),resume='r'.repeat(43);await f.relay.fetch(request(`/v2/hosts/${id}/connect`,'a'.repeat(43)));const host=f.sockets[0];
 await f.relay.webSocketMessage(host,JSON.stringify({type:'offer',pairingId:pair,capabilityHash:await hash(cap),expiresAt:Date.now()+120000}));await f.relay.fetch(request(`/v2/pairings/${pair}/claim?hostId=${id}`,cap));const phone=f.sockets[1];
 await f.relay.webSocketMessage(host,JSON.stringify({type:'recovery',id:phone.a.id,credentialHash:await hash(resume)}));phone.close();
 assert.equal((await f.relay.fetch(request(`/v2/pairings/${pair}/resume?hostId=${id}`,cap))).status,401);
 assert.equal((await f.relay.fetch(request(`/v2/pairings/${pair}/resume?hostId=${id}`,resume))).status,101);
 assert.equal(JSON.parse(host.sent.at(-1)).resume,true);
 assert.equal((await f.relay.fetch(request(`/v2/pairings/${pair}/claim?hostId=${id}`,cap))).status,401);
});
