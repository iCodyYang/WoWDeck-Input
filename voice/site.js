// Runs only in the plugin's dedicated Doubao page. Browser-managed cookies never leave it.
(() => {
  if (location.origin !== 'https://www.doubao.com' || window.__wdi) return;
  let auth = 'checking', qr = '', expires = 0, loginRequested = true, lastClick = 0;
  let loginAttempts = 0, qrModeRequested = false, refreshRequested = false;
  const loadedAt = Date.now();
  function setAuth(next) {
    if (next === 'guest' && auth === 'signed') {loginAttempts=0;qrModeRequested=false;}
    auth = next;
    if (next === 'signed') { qr = ''; loginRequested = false; }
    if (next === 'guest') loginRequested = true;
  }
  let active, finalText, lastSequence = 0;
  function observe(url, data, status) {
    const u = new URL(url, location.href);
    if (u.origin === 'https://accounts.doubao.com' && u.pathname.replace(/\/$/,'') === '/passport/web/get_qrcode') {
      let img = data?.data?.qrcode;
      if (typeof img === 'string' && /^iVBORw0KGgo[A-Za-z0-9+/=]+$/.test(img)) img = 'data:image/png;base64,' + img;
      if ([0,'0'].includes(data?.data?.error_code) && typeof img === 'string' && img.length < 250000 &&
          /^data:image\/png;base64,iVBORw0KGgo[A-Za-z0-9+/=]+$/.test(img)) {
        if (auth === 'signed') return;
        setAuth('guest');
        qr = img;
        refreshRequested = false;
        expires = Date.now() + 120000; // conservative local cap; the official page owns ticket expiry
      }
    }
    if (u.origin === location.origin && u.pathname.endsWith('/alice/profile/self')) {
      if (data?.code === 0 && data?.data?.profile_brief) setAuth('signed');
      else if (status === 401 || [710012001, 710022013].includes(data?.code)) setAuth('guest');
    }
  }
  function watches(url) {
    try {
      const u = new URL(url, location.href);
      return (u.origin === location.origin && u.pathname.endsWith('/alice/profile/self')) ||
        (u.origin === 'https://accounts.doubao.com' && u.pathname.replace(/\/$/,'') === '/passport/web/get_qrcode');
    } catch (_) { return false; }
  }
  const nativeFetch = window.fetch;
  window.fetch = function(input, ...options) {
    const promise = nativeFetch.call(this, input, ...options);
    const url = typeof input === 'string' ? input : input?.url || String(input);
    if (watches(url)) promise.then(async r => observe(url, await r.clone().json(), r.status)).catch(() => {});
    return promise;
  };
  const open = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(method, url, ...args) {
    if (watches(url)) this.addEventListener('load', () => {
      try { observe(url, this.responseType === 'json' ? this.response : JSON.parse(this.responseText), this.status); } catch (_) {}
    }, {once:true});
    return open.call(this, method, url, ...args);
  };
  function stop() {
    const job = active;
    active = null;
    if (!job) return;
    job.finished = true;
    clearTimeout(job.deadline); clearTimeout(job.quiet); clearTimeout(job.life);
    if (job.socket) {
      job.socket.onclose = job.socket.onerror = job.socket.onmessage = job.socket.onopen = null;
      job.socket.close();
    }
  }
  function startStream(id) {
    stop(); finalText = null;
    const job = active = {id, finished:false, queue:[], bytes:0, sent:0, responses:0,
      opened:null, tail:false, ending:false, started:Date.now(), ended:null};
    const current = () => active === job && !job.finished;
    let last = '';
    function done(error) {
      if (!current()) return;
      const now = Date.now();
      const stats = {audio_bytes:job.bytes, sent_bytes:job.sent, responses:job.responses,
        total_ms:now-job.started, final_ms:job.ended === null ? 0 : now-job.ended};
      if (job.opened !== null) stats.connect_ms = job.opened-job.started;
      stop();
      finalText = {id, text:error ? '' : last.slice(0,1500), error, stats};
    }
    function waitForFinal() {
      clearTimeout(job.quiet);
      // Require a response after the tail, not just text left from mid-speech.
      if (current() && job.tail && last && job.responses > job.responsesAtTail)
        job.quiet = setTimeout(() => done(''), 450);
    }
    function flush() {
      if (!current() || job.opened === null) return;
      try {
        for (const bytes of job.queue) {
          for (let offset=0;offset<bytes.length;offset+=6400) {
            const chunk=bytes.subarray(offset,offset+6400);
            job.socket.send(chunk);job.sent+=chunk.length;
          }
        }
        job.queue=[];
        if (job.ending && !job.tail) {
          // Same 200 ms tail as upstream, in two 100 ms frames. It is sent
          // immediately; there is no timer per audio frame or guessed JSON EOS.
          job.socket.send(new Uint8Array(3200));job.socket.send(new Uint8Array(3200));
          job.tail=true;job.responsesAtTail=job.responses;
          clearTimeout(job.deadline);
          job.deadline=setTimeout(() => done(job.responses
            ? '没有收到完整的识别结果，请检查麦克风后重试'
            : '语音服务没有返回结果，请检查网络后重试'),6000);
        }
      } catch (_) { done('语音发送中断，请重试'); }
    }
    job.feed = audio => {
      if (!current() || job.ending) return;
      try {
        const bytes=Uint8Array.from(atob(audio), c=>c.charCodeAt(0));
        if (bytes.length % 2 || job.bytes+bytes.length > 640000) return done('录音数据不完整，请重新说一次');
        job.bytes+=bytes.length;job.queue.push(bytes);flush();
      } catch (_) { done('录音数据无法读取，请重新说一次'); }
    };
    job.finish = () => {
      if (!current() || job.ending) return;
      job.ending=true;job.ended=Date.now();clearTimeout(job.life);flush();
    };
    try {
      if (auth !== 'signed') { done('请先恢复豆包连接');return job; }
      function readIds(key) {
        // Some versions store long account IDs as JSON integers, beyond JS safe precision.
        const raw = localStorage.getItem(key) || '{}';
        return JSON.parse(raw.replace(/("(?:web_id|user_unique_id)"\s*:\s*)(\d+)(?=\s*[,}])/g, '$1"$2"'));
      }
      const device = readIds('samantha_web_web_id');
      const tea = readIds('__tea_cache_tokens_497858');
      const deviceId = device.web_id || tea.user_unique_id || tea.web_id;
      if (!deviceId || !tea.web_id) return done('豆包网页未提供听写参数，请重新连接');
      const params = new URLSearchParams({
        version_code:'20800', language:'zh', device_platform:'web', aid:'497858', real_aid:'497858',
        pkg_type:'release_version', pc_version:'3.12.3', region:'', sys_region:'', samantha_web:'1',
        'use-olympus-account':'1', format:'pcm', device_id:String(deviceId), web_id:String(tea.web_id),
        tea_uuid:String(tea.web_id), web_tab_id:crypto.randomUUID()
      });
      const socket = job.socket = new WebSocket('wss://ws-samantha.doubao.com/samantha/audio/asr?' + params);
      job.deadline=setTimeout(() => done('语音服务连接超时，请检查网络后重试'),5000);
      job.life=setTimeout(() => done('录音连接超时，请松开后重试'),25000);
      socket.onopen = () => {
        if (!current()) return;
        job.opened=Date.now();clearTimeout(job.deadline);flush();
      };
      socket.onmessage = event => {
        if (!current()) return;
        let d; try { d = JSON.parse(event.data); } catch (_) { return done('无法读取豆包响应'); }
        job.responses++;
        if ([710012001,710022013].includes(d.code)) {
          setAuth('guest');loginRequested=true;
          return done('豆包提示登录已失效，请重新扫码');
        }
        if (d.code) return done('豆包拒绝听写，请检查登录状态后重试');
        if (d.event === 'finish') return done(job.tail ? (last ? '' : '没有识别到文字') : '识别连接提前结束，请重新按住说话');
        if (d.event === 'result') {
          if (typeof d.result?.Text === 'string' && d.result.Text.trim()) last=d.result.Text.trim();
          waitForFinal();
        }
      };
      socket.onerror = () => done('语音服务连接失败，请检查网络后重试');
      socket.onclose = e => done(job.tail && last && e.code===1000 ? '' : '语音连接中断，请重试');
    } catch (_) { done('豆包听写接口不可用'); }
    return job;
  }
  window.__wdi = input => {
    // Acknowledged batches preserve every chunk even if a browser tick is late.
    const commands=Array.isArray(input?.commands) ? input.commands : input ? [input] : [];
    for (const cmd of commands) {
      if (!Number.isSafeInteger(cmd.seq) || cmd.seq <= lastSequence) continue;
      lastSequence=cmd.seq;
      if (cmd.action==='login' || cmd.action==='restore') {
        loginRequested=true; loginAttempts=0; qrModeRequested=false;
        if (cmd.action==='login' && auth!=='signed') {qr='';refreshRequested=true;}
      }
      if (cmd.action==='start') startStream(cmd.id);
      if (cmd.action==='chunk' && active?.id===cmd.id) active.feed(cmd.audio);
      if (cmd.action==='finish' && active?.id===cmd.id) active.finish();
      if (cmd.action==='audio') { const job=startStream(cmd.seq);job?.feed(cmd.audio);job?.finish(); }
      if (cmd.action==='cancel') { stop();finalText=null; }
    }
    // Allow the official page to hydrate and verify its saved account before opening a login dialog.
    if (qr && Date.now()>=expires) {qr='';refreshRequested=true;}
    if (loginRequested && auth !== 'signed' && !qr && Date.now()-loadedAt > 4000 && Date.now()-lastClick > 2500) {
      const buttons = Array.from(document.querySelectorAll('button, [role="button"]')).filter(b=>b.getClientRects().length);
      const refresh = refreshRequested && buttons.find(b=>/^(刷新二维码|重新获取二维码|刷新|Refresh QR code)$/i.test(b.textContent.trim()));
      const qrMode = !qrModeRequested && buttons.find(b=>/^(扫码登录|二维码登录|Scan to log in|QR code login)$/i.test(b.textContent.trim()));
      const hasDialog = Array.from(document.querySelectorAll('[role="dialog"], [aria-modal="true"]')).some(d=>d.getClientRects().length);
      const login = !hasDialog && loginAttempts<3 && buttons.find(b=>/^(登录|登录\/注册|登录注册|Log in|Sign in)$/i.test(b.textContent.trim()));
      if (refresh) {lastClick=Date.now();refreshRequested=false;refresh.click();}
      else if (qrMode) {lastClick=Date.now();qrModeRequested=true;qrMode.click();}
      else if (login) {lastClick=Date.now();loginAttempts++;login.click();}
    }
    const state = {seq:lastSequence, auth, streaming:!!active, signedIn:auth==='signed', qr:auth==='guest' && Date.now()<expires ? qr : '', result:finalText};
    finalText = null;
    return JSON.stringify(state);
  };
})();
