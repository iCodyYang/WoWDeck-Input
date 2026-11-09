import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

const code=readFileSync(new URL('../voice/site.js',import.meta.url),'utf8');
function page() {
 let now=1000, response={}, buttons=[], dialog=false;
 class Xhr {open(){}}
 const realm={window:{fetch:async()=>({status:200,clone:()=>({json:async()=>response})})},
   XMLHttpRequest:Xhr,location:new URL('https://www.doubao.com/chat/'),
   document:{querySelectorAll:selector=>selector.startsWith('button')?buttons:dialog?[{getClientRects:()=>[{}]}]:[]},
   Date:{now:()=>now},URL,crypto,setTimeout,clearTimeout};
 vm.runInNewContext(code,realm);
 return {run:cmd=>JSON.parse(realm.window.__wdi(cmd)),advance:()=>{now+=5000;},
   buttons:value=>{buttons=value;},dialog:value=>{dialog=value;},
   respond:async(url,data)=>{response=data;await realm.window.fetch(url);await new Promise(r=>setImmediate(r));}};
}
const button=text=>({textContent:text,count:0,getClientRects:()=>[{}],click(){this.count++;}});
const p=page(),login=button('Sign in');p.buttons([login]);
for(let i=0;i<12;i++){p.advance();p.run(null);}
assert.equal(login.count,3,'missing QR must not repeatedly toggle the login dialog');
p.run({seq:1,action:'login'});
assert.equal(login.count,4,'explicit retry allows a fresh attempt');
p.dialog(true);p.advance();p.run(null);assert.equal(login.count,4,'open dialog is not toggled closed');
const qrMode=button('扫码登录');p.buttons([login,qrMode]);p.advance();p.run(null);p.advance();p.run(null);
assert.equal(qrMode.count,1,'select QR mode once rather than clicking continuously');
const raw='iVBORw0KGgoAAA==',prefix='data:image/png;base64,';
await p.respond('https://untrusted.example/passport/web/get_qrcode',{data:{error_code:0,qrcode:raw}});
assert.equal(p.run(null).qr,'');
await p.respond('https://accounts.doubao.com/passport/web/get_qrcode',{data:{error_code:'0',qrcode:raw}});
assert.equal(p.run(null).qr,prefix+raw,'official raw PNG response is accepted');
p.run({seq:2,action:'login'});
const refresh=button('刷新二维码');p.buttons([refresh]);p.advance();p.run(null);p.advance();p.run(null);
assert.equal(refresh.count,1,'refresh current official dialog without restarting the browser');
const q=page();
await q.respond('https://accounts.doubao.com/passport/web/get_qrcode/',{data:{error_code:0,qrcode:'data:image/svg+xml;base64,AAAA'}});
assert.equal(q.run(null).qr,'','only PNG is returned to the plugin');
await q.respond('https://accounts.doubao.com/passport/web/get_qrcode/',{data:{error_code:0,qrcode:prefix+raw}});
for(let i=0;i<25;i++)q.advance();
assert.equal(q.run(null).qr,'','expired QR is cleared');
console.log('PASS: bounded login actions, dialog protection, QR mode, trusted PNG formats, expiry and in-page refresh');
