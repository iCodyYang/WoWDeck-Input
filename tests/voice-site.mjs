import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const code=readFileSync(new URL('../voice/site.js',import.meta.url),'utf8');
let clicked=0, ws;
let now=1000;
const timers=[];
class Xhr { open(){} }
class Socket {
  constructor(url){this.url=url;this.sent=[];ws=this;}
  send(data){this.sent.push(data);}
  close(){this.closed=true;}
}
const realm={window:{fetch:async()=>({clone:()=>({json:async()=>realm.response})})},
  WebSocket:Socket, XMLHttpRequest:Xhr, location:new URL('https://www.doubao.com/chat/'),
  document:{querySelectorAll:selector=>selector.startsWith('button')?[{textContent:'登录',getClientRects:()=>[{}],click:()=>clicked++}]:[]},
  localStorage:{getItem:key=>key.startsWith('__tea')?'{"web_id":1111111111111111111,"user_unique_id":"34"}':'{}'},
  Date:{now:()=>now}, crypto, Uint8Array, URL, URLSearchParams, atob,
  setTimeout:(fn,ms)=>{timers.push({fn,ms});return setTimeout(fn,ms);}, clearTimeout};
vm.runInNewContext(code,realm);
const run=cmd=>JSON.parse(realm.window.__wdi(cmd));
const final=()=>{const {stats,...result}=run(null).result;return result;};
async function respond(url,data){ realm.response=data; await realm.window.fetch(url); await new Promise(r=>setImmediate(r)); }
const profile='https://www.doubao.com/alice/profile/self';
assert.equal(run({seq:1,action:'login'}).signedIn,false); assert.equal(clicked,0); now+=5000; run(null); assert.equal(clicked,1);
const img='data:image/png;base64,iVBORw0KGgoAAA==';
await respond('https://untrusted.example/passport/web/get_qrcode/',{data:{error_code:0,qrcode:img}});
assert.equal(run(null).qr,'');
await respond('https://accounts.doubao.com/passport/web/get_qrcode/',{data:{error_code:0,qrcode:img}});
assert.equal(run(null).qr,img);
run({seq:2,action:'audio',audio:'AAA='}); assert.equal(ws,undefined);
await respond(profile,{code:0,data:{profile_brief:{nickname:'test'}}});
assert.equal(run(null).signedIn,true);assert.equal(run(null).qr,'');
await respond(profile,{code:503});
await respond(profile,{code:0,data:{}});
assert.equal(run(null).auth,'signed','a transient or incomplete profile response must preserve the verified login');
run({seq:3,action:'audio',audio:Buffer.alloc(6400).toString('base64')});
assert.equal(new URL(ws.url).origin,'wss://ws-samantha.doubao.com');
assert.equal(new URL(ws.url).searchParams.get('web_id'),'1111111111111111111');
ws.onopen();await new Promise(r=>setTimeout(r,35));assert.equal(ws.sent.length,3);
ws.onmessage({data:JSON.stringify({event:'result',result:{Text:'队'}})});
ws.onmessage({data:JSON.stringify({event:'result',result:{Text:'队伍集合'}})});
ws.onmessage({data:'{"event":"finish"}'});
assert.deepEqual(final(),{id:3,text:'队伍集合',error:''});
assert.equal(run(null).result,null);assert.equal(ws.closed,true);
run({seq:4,action:'audio',audio:'AAA='}); ws.onerror();
assert.equal(run(null).result.text,'');
run({seq:5,action:'audio',audio:'AAA='});run({seq:6,action:'cancel'});assert.equal(ws.closed,true);assert.equal(run(null).result,null);
await respond(profile,{code:710012001});
assert.equal(run(null).auth,'guest');

await respond(profile,{code:0,data:{profile_brief:{nickname:'test'}}});
run({seq:7,action:'audio',audio:Buffer.alloc(6400).toString('base64')});
const previous=ws, lateMessage=ws.onmessage, lateOpen=ws.onopen, lateError=ws.onerror;
const lateDeadline=timers.findLast(t=>t.ms===5000).fn;
const lateLife=timers.findLast(t=>t.ms===25000).fn;
ws.onopen();
run({seq:8,action:'cancel'});
run({seq:9,action:'audio',audio:'AAA='});
const fresh=ws;
lateMessage({data:JSON.stringify({event:'result',result:{Text:'旧句'}})});
lateMessage({data:'{"code":710012001}'}); // stale auth errors cannot log out the new session
lateOpen();lateError();lateDeadline();lateLife();
assert.equal(run(null).auth,'signed');
assert.equal(run(null).result,null);
assert.equal(fresh.closed,undefined);
assert.equal(previous.sent.length,3,'old callbacks must not send into either socket');
fresh.onopen();await new Promise(r=>setTimeout(r,25));
const completedMessage=fresh.onmessage;
completedMessage({data:JSON.stringify({event:'result',result:{Text:'本句内容'}})});
const lateQuiet=timers.at(-1).fn;
completedMessage({data:'{"event":"finish"}'});
assert.deepEqual(final(),{id:9,text:'本句内容',error:''});
completedMessage({data:'{"event":"finish"}'});lateQuiet();
assert.equal(run(null).result,null,'a consumed final result must never be recreated');

// A repeated phrase is valid new speech. Scope by request identity, not by text.
run({seq:10,action:'audio',audio:'AAA='});ws.onopen();await new Promise(r=>setTimeout(r,25));
lateQuiet();completedMessage({data:'{"event":"finish"}'});
assert.equal(ws.closed,undefined);
ws.onmessage({data:JSON.stringify({event:'result',result:{Text:'本句内容'}})});
ws.onmessage({data:'{"event":"finish"}'});
assert.deepEqual(final(),{id:10,text:'本句内容',error:''});
console.log('PASS: official QR origin, guest gating, ASR frames, final corrections, failure and cancellation');
console.log('PASS: stale socket/timer isolation, consumed results stay final, consecutive identical phrases');

// Real-time commands: buffer during connection, then send while still held.
run({seq:11,action:'start',id:11});
const streaming=ws;
run({seq:12,action:'chunk',id:11,audio:Buffer.alloc(3200,1).toString('base64')});
assert.equal(streaming.sent.length,0);
streaming.onopen();assert.equal(streaming.sent.length,1);
const batch={seq:14,commands:[
 {seq:13,action:'chunk',id:11,audio:Buffer.alloc(3200,2).toString('base64')},
 {seq:14,action:'chunk',id:11,audio:Buffer.alloc(3200,3).toString('base64')}
]};
assert.equal(run(batch).seq,14);run(batch);
assert.equal(streaming.sent.length,3,'browser replay must not duplicate audio');
assert.deepEqual(streaming.sent.map(b=>b[0]),[1,2,3]);
streaming.onmessage({data:JSON.stringify({event:'result',result:{Text:'还在说'}})});
assert.equal(run(null).result,null,'partials never paste while the key is held');
now+=1000;run({seq:15,action:'finish',id:11});
assert.equal(streaming.sent.length,5);
assert.deepEqual(streaming.sent.slice(-2).map(b=>b.length),[3200,3200]);
assert.equal(timers.at(-1).ms,6000,'mid-speech text alone cannot trigger quiet completion');
streaming.onmessage({data:JSON.stringify({event:'result',result:{Text:'这是最终一句'}})});
assert.equal(timers.at(-1).ms,450);now+=450;timers.at(-1).fn();
const completed=run(null).result;
assert.equal(completed.text,'这是最终一句');
assert.equal(completed.stats.audio_bytes,9600);
assert.equal(completed.stats.sent_bytes,9600);
assert.equal(completed.stats.final_ms,450);
run({seq:16,action:'chunk',id:11,audio:'AAA='});
assert.equal(run(null).result,null);

run({seq:17,action:'start',id:17});
const pending=ws;
run({seq:18,action:'chunk',id:11,audio:'AAA='});
pending.onopen();assert.equal(pending.sent.length,0,'previous utterance audio is ignored');
run({seq:19,action:'cancel'});assert.equal(pending.closed,true);
run({seq:20,action:'start',id:20});timers.findLast(t=>t.ms===5000).fn();
assert.match(run(null).result.error,/连接超时/);
assert.equal(run(null).auth,'signed','network timeout is not a logout');
console.log('PASS: streaming before release, ordered/replayed batches, tail response, timing counters and connection timeout');
