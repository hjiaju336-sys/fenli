/* common.js — Shared utilities for fenli project (desktop index.html + mobile m.html)
   Set BEFORE loading this script:
     window._isMobile = true   (for m.html)
     window._isMobile = undefined/false  (for index.html)
*/
(function(){
  "use strict";
  var _isMobile = window._isMobile;

  // ═══ Unified storage ─────────────────────────────────────────
  var _pre = _isMobile ? 'm_' : 'mvp_';
  window._Stor = {
    get: function(k,d){ try{var v=localStorage.getItem(_pre+k); return v?JSON.parse(v):d; }catch(e){return d;} },
    set: function(k,v){ localStorage.setItem(_pre+k, JSON.stringify(v)); },
    getS: function(k,d){ return localStorage.getItem(_pre+k)||d; },
    setS: function(k,v){ localStorage.setItem(_pre+k, v); },
    remove: function(k){ localStorage.removeItem(_pre+k); }
  };

  // ═══ 工具函数 ─────────────────────────────────────────
  window.escHTML = function escHTML(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;')};
  window.esc = window.escHTML; // alias for mobile compatibility

  window._auth = function _auth(){return window._token||window._Stor.getS('token','')};

  // ═══ 认证 fetch ─────────────────────────────────────────
  window._fetch = async function _fetch(url, opts){
    opts = opts || {};
    opts.headers = opts.headers || {};
    if(!opts.headers['Authorization']){
      opts.headers['Authorization'] = 'Bearer ' + window._auth();
    }
    try {
      var resp = await fetch(url, opts);
      if(resp.status === 401){
        window._Stor.remove('token');
        window._token = '';
        showToast('登录已过期，请重新登录', 'error');
        setTimeout(function(){
          if(_isMobile) window.navigateTo('pg-login');
          else window.navTo('page-login');
        }, 1500);
        throw new Error('Unauthorized');
      }
      var data = await resp.json();
      if(data.error) throw new Error(data.error);
      return data;
    } catch(e){
      if(e.message !== 'Unauthorized'){
        showToast('网络错误: ' + e.message, 'error');
      }
      throw e;
    }
  };

  // ═══ _fetchOk (desktop helper for then-style fetch with toast) ──
  window._fetchOk = function _fetchOk(url,opts,okMsg,errMsg,cb){
    var b=opts&&opts.body;opts=opts||{};
    opts.headers=opts.headers||{};
    if(!opts.headers['Content-Type']&&b)opts.headers['Content-Type']='application/json';
    if(!opts.headers['Authorization'])opts.headers['Authorization']='Bearer '+window._auth();
    return fetch(url,opts).then(function(r){
      if(r.status===401){
        window._Stor.remove('token');window._token='';
        showToast('登录已过期，请重新登录','error');
        setTimeout(function(){
          if(_isMobile) window.navigateTo('pg-login');
          else window.navTo('page-login');
        },1500);
        if(cb)cb(null,true);
        throw new Error('Unauthorized');
      }
      return r.json();
    }).then(function(d){
      if(d.error){showToast((errMsg||'操作失败')+': '+d.error,'error');if(cb)cb(d,true)}
      else{showToast(okMsg||'操作成功','success');if(cb)cb(d,false)}
    }).catch(function(e){if(e.message!=='Unauthorized'){showToast((errMsg||'网络错误')+': '+e.message,'error');if(cb)cb(null,true)}})
  };

  // ═══ Toast 通知 ─────────────────────────────────────────
  window.showToast = function showToast(msg, type){
    type = type || 'info';
    var icons = {success:'✓', error:'✗', info:'ℹ', loading:'◌'};
    var el = document.createElement('div'); el.className = 'toast toast-'+type;
    el.textContent = (icons[type]||'') + ' ' + msg;
    var tc = document.getElementById('toast-container');
    if(tc){
      tc.appendChild(el);
    }else{
      // fallback: append to body
      el.style.cssText = 'position:fixed;top:16px;left:50%;transform:translateX(-50%);z-index:9999;padding:10px 22px;border-radius:6px;font-size:13px;font-family:var(--font);color:#fff;box-shadow:0 4px 16px rgba(0,0,0,.3);pointer-events:none;white-space:nowrap';
      if(type==='success') el.style.background = '#3a7d3a';
      else if(type==='error') el.style.background = '#8b2020';
      else if(type==='info') el.style.background = '#2a5a8a';
      else el.style.background = '#4a3a5a';
      document.body.appendChild(el);
    }
    setTimeout(function(){ if(el.parentNode) el.remove(); }, 4000);
  };
  window.toast = window.showToast; // alias for mobile compatibility

  // ═══ 确认弹窗 ─────────────────────────────────────────
  window.showConfirm = function showConfirm(msg, cb){
    if(window._isMobile){
      // Use existing modal-confirm element in m.html
      document.getElementById('confirm-msg').textContent = msg;
      document.getElementById('confirm-yes').onclick = function(){ closeModal('modal-confirm'); cb(); };
      document.getElementById('modal-confirm').classList.add('active');
    }else{
      // Desktop: create popup dynamically
      // _cleanPopups() - clean up dynamic popups but keep persistent ones
      document.querySelectorAll('.popup-overlay').forEach(function(el){
        if(el.id !== 'popup-api' && el.id !== 'popup-saves' && el.id !== 'popup-ending' && el.id !== 'popup-debug'){
          el.remove();
        }
      });
      var o = document.createElement('div'); o.className = 'popup-overlay active';
      o.innerHTML = '<div class="popup" style="text-align:center"><div style="margin-bottom:14px">'+escHTML(msg)+'</div><div style="display:flex;gap:10px;justify-content:center"><button class="btn btn-primary" id="_cyes">确认</button><button class="btn btn-secondary" id="_cno">取消</button></div></div>';
      document.body.appendChild(o);
      o.querySelector('#_cyes').onclick = function(){ o.remove(); cb(); };
      o.querySelector('#_cno').onclick = function(){ o.remove(); };
    }
  };

  // ═══ 引号高亮 ─────────────────────────────────────────
  window.highlightQuotes = function highlightQuotes(text){
    var safe = escHTML(text);
    safe = safe.replace(/\n/g,'<br>');
    var cls = window._isMobile ? 'quote-hl' : 'quote-highlight';
    safe = safe.replace(/&quot;(.*?)&quot;/g,'<span class="'+cls+'">"$1"</span>');
    safe = safe.replace(/「(.*?)」/g,'<span class="'+cls+'">「$1」</span>');
    return safe;
  };
  window.highlightMQ = window.highlightQuotes; // alias for mobile compatibility

  // ═══ NPC名字高亮 ─────────────────────────────────────────
  window.highlightNPCs = function highlightNPCs(html){
    var tags = window._isMobile ? (window._lastTags||{}) : (window._lastTagsByCat||{});
    var chars = tags.character || [];
    if(!chars.length) return html;
    var names = [], seen = {};
    var npcColors = ['#d4a574','#b84a5c','#7b68ae','#6a9aca','#68ae8a','#ca9a6a','#ae688a','#8aae68'];
    for(var i=0;i<chars.length;i++){
      var n = chars[i].tag_name||'';
      if(n&&!seen[n]&&n.length>=2&&n!=='玩家'&&n!=='你'&&n!=='自己'){seen[n]=true;names.push(n)}
    }
    if(!names.length) return html;
    names.sort(function(a,b){return b.length-a.length});
    for(var j=0;j<names.length;j++){
      var nm = names[j], color = npcColors[j%npcColors.length];
      var escapedName = nm.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
      var re = new RegExp('('+escapedName+')','g');
      html = html.replace(re,'<span style="color:'+color+';font-weight:700;text-shadow:0 0 6px '+color+'44">$1</span>');
    }
    return html;
  };
  window.highlightMNPCs = window.highlightNPCs; // alias for mobile compatibility

  // ═══ M4: WS断网遮罩 ─────────────────────────────────────────
  window._wsFailTimer = null;
  window._wsEverConnected = false;
  window.showWSOverlay = function showWSOverlay(){
    document.getElementById('ws-overlay').classList.add('active');
    document.getElementById('ws-text').textContent = '网络已断开，正在重连...';
    document.getElementById('ws-text').classList.remove('clickable');
    document.getElementById('ws-text').onclick = null;
  };
  window.hideWSOverlay = function hideWSOverlay(){
    document.getElementById('ws-overlay').classList.remove('active');
    clearTimeout(window._wsFailTimer);
    window._wsFailTimer = null;
  };
  window.wsReconnectFailed = function wsReconnectFailed(){
    document.getElementById('ws-text').textContent = '重连失败，点击刷新';
    document.getElementById('ws-text').classList.add('clickable');
    document.getElementById('ws-text').onclick = function(){ location.reload(); };
  };

  // ═══ WebSocket 连接 ─────────────────────────────────────────
  window.connectWS = function connectWS(){
    if(window._ws&&window._ws.readyState===WebSocket.OPEN) return;
    var tok = window._token||window._Stor.getS('token','');
    window._ws = new WebSocket((location.protocol==='https:'?'wss:':'ws:')+'//'+location.host+'/ws?token='+encodeURIComponent(tok));
    window._ws.onopen = function(){
      if(_isMobile){
        document.getElementById('chat-status').textContent = '已连接';
        document.getElementById('chat-status').style.color = '#4a4';
      }else{
        var s = document.getElementById('game-status'); if(s){ s.textContent = '已连接'; s.style.color = '#4a4'; }
      }
      hideWSOverlay();
      if(window._wsEverConnected) showToast('已重连','success');
      window._wsEverConnected = true;
      clearTimeout(window._wsFailTimer);
      window._wsFailTimer = null;
    };
    window._ws.onclose = function(){
      window._busy = false;
      if(_isMobile){
        if(window._curPage==='pg-chat'){
          document.getElementById('chat-status').textContent = '断开,重连中...';
          document.getElementById('chat-status').style.color = '#a44';
          showWSOverlay();
          setTimeout(connectWS, 3000);
          if(!window._wsFailTimer) window._wsFailTimer = setTimeout(wsReconnectFailed, 30000);
        }
      }else{
        if(window._cp==='page-game'){
          var s = document.getElementById('game-status'); if(s){ s.textContent = '断开,重连中...'; s.style.color = '#a44'; }
          showWSOverlay();
          clearTimeout(window._reconnectTimer);
          window._reconnectTimer = setTimeout(connectWS, 3000);
          if(!window._wsFailTimer) window._wsFailTimer = setTimeout(wsReconnectFailed, 30000);
        }
      }
      if(!_isMobile) setBtns(false);
    };
    window._ws.onmessage = function(ev){
      try{ handleWS(JSON.parse(ev.data)); } catch(e){ console.error('WS parse error:', e); }
    };
  };

  // ═══ setBtns / showThinking / showStatus / _insertErrorMsg (desktop) ──
  window.setBtns = function setBtns(b){
    window._busy = b;
    if(window._isMobile){
      document.getElementById('btn-send').style.display = b?'none':'flex';
      document.getElementById('btn-stop').style.display = b?'flex':'none';
    }else{
      document.getElementById('btn-send').style.display = b?'none':'';
      document.getElementById('btn-cancel').style.display = b?'':'none';
    }
  };
  window.showThinking = function showThinking(){
    if(window._isMobile){
      var cs = document.getElementById('chat-status');
      if(cs) cs.innerHTML = 'AI思考中<span class="thinking-dots"><span></span><span></span><span></span></span>';
    }else{
      var s = document.getElementById('game-status');
      if(s) s.innerHTML = 'AI思考中<span class="thinking-dots"><span></span><span></span><span></span></span>';
    }
  };
  window.showStatus = function showStatus(text,color){
    if(window._isMobile){
      var cs = document.getElementById('chat-status'); if(cs){ cs.textContent = text; cs.style.color = color||'var(--text2)'; }
    }else{
      var s = document.getElementById('game-status'); if(s){ s.textContent = text; s.style.color = color||'var(--ink-light)'; }
    }
  };
  window._insertErrorMsg = function _insertErrorMsg(msg){
    if(window._isMobile){
      var sk = document.getElementById('chat-msgs').querySelector('.skeleton'); if(sk) sk.remove();
      window._busy = false;
      document.getElementById('btn-send').style.display = 'flex';
      document.getElementById('btn-stop').style.display = 'none';
      document.getElementById('chat-status').textContent = '错误';
      var errDiv = document.createElement('div'); errDiv.className = 'msg-error';
      errDiv.innerHTML = '<span>⚠ '+escHTML((msg||'AI调用失败'))+'</span> <button onclick="this.parentElement.remove();mRetrySend()">点击重试</button>';
      document.getElementById('chat-msgs').appendChild(errDiv);
      scrollChat();
      showToast(msg,'error');
    }else{
      var d = document.createElement('div'); d.className = 'msg-error';
      d.innerHTML = '<span>'+escHTML(msg)+'</span> <button onclick="retryLastInput();this.parentElement.remove()">点击重试</button>';
      document.getElementById('chat-msgs').appendChild(d);
      var msgs = document.getElementById('chat-msgs'); msgs.scrollTop = msgs.scrollHeight;
    }
  };
  window.retryLastInput = function retryLastInput(){
    if(window._isMobile){
      var last = window._lastUserInput||'';
      if(last){ document.getElementById('chat-input').value = last; sendMsg(); }
      else{ showToast('无上一轮输入可重试','info'); }
    }else{
      var inp = document.getElementById('game-input'), last = window._lastUserInput||'';
      if(last){ inp.value = last; sendMsg(); }
      else{ showToast('无上一轮输入可重试','info'); }
    }
  };

  // ═══ WS 消息分发 ─────────────────────────────────────────
  window.handleWS = function handleWS(d){
    if(window._isMobile){
      // ──── MOBILE VERSION ────
      if(d.type==='init_state'){
        document.getElementById('chat-world').textContent = d.world_name||'未知副本';
        if(d.world_book) window._worldBook = d.world_book;
        if(d.all_tags_by_category) window._lastTags = d.all_tags_by_category;
        if(window.renderSideDrawer) renderSideDrawer();
        if(d.world_name){ var sn = document.getElementById('sd-world-name'); if(sn) sn.textContent = d.world_name; }
        if(d.world_desc){ var sd2 = document.getElementById('sd-world-desc'); if(sd2) sd2.textContent = d.world_desc; }
        window._lastPlayerDetail = d.player_detail||{};
        if(d.player_detail){ var pd = d.player_detail; var pdEl = document.getElementById('chat-pdetail'); if(pdEl){ var hp=pd.hp||pd['血量']||pd['HP']||pd['生命值']||'?',maxHp=pd.max_hp||pd['最大血量']||pd['最大生命值']||hp,sanity=pd.sanity||pd['理智']||pd['SAN']||pd['理智值']||'?',maxSan=pd.max_sanity||pd['最大理智']||pd['最大理智值']||sanity; pdEl.style.display='inline'; pdEl.textContent='❤️ '+hp+'/'+maxHp+' | 🧠 '+sanity+'/'+maxSan; } }
        var msgs = document.getElementById('chat-msgs');
        var sk = msgs.querySelector('.skeleton'); if(sk) sk.remove();
        var html = '';
        var saved = window._savedMessages||[];
        var _renderMsg = window.renderMsg || function(r,c){return window.esc(c);};
        if(saved.length>0){
          for(var si=0;si<saved.length;si++){ var sm=saved[si]; html+=_renderMsg(sm.role==='user'?'user':(sm.role==='ai'?'ai':'system'),sm.content); }
          window._savedMessages=null;
        }else if(d.world_intro){ html+=_renderMsg('system',d.world_intro); }
        if(d.opening_monologue&&!saved.length) html+=_renderMsg('ai',d.opening_monologue);
        if(!html) html='<div class="chat-msg system"><div class="bubble">副本已加载，等待AI响应...</div></div>';
        msgs.innerHTML = html; if(window.scrollChat) scrollChat();
        _setupMsgPagination(); _initMsgBuffer();
        if(d.ai_avatar_url) window._aiAvatar = d.ai_avatar_url;
      }else if(d.type==='narrative_chunk'){
        var msgs = document.getElementById('chat-msgs'), last = msgs.lastElementChild;
        if(!last||!last.classList.contains('chat-msg')||!last.classList.contains('ai')){
          last = document.createElement('div'); last.className = 'chat-msg ai';
          last.innerHTML = '<div class="avatar">🤖</div><div class="bubble"></div>';
          msgs.appendChild(last);
        }
        var skEl = msgs.querySelector('.skeleton'); if(skEl) skEl.remove();
        last.querySelector('.bubble').textContent += d.text;
        if(window.scrollChat) scrollChat();
      }else if(d.type==='turn_complete'){
        var skEl2 = document.getElementById('chat-msgs').querySelector('.skeleton'); if(skEl2) skEl2.remove();
        window._busy = false; window._turnCount++;
        document.getElementById('btn-send').style.display = 'flex';
        document.getElementById('btn-stop').style.display = 'none';
        document.getElementById('chat-status').textContent = 'OK '+(d.latency_ms||0)+'ms';
        document.getElementById('chat-status').style.color = '#4a4';
        if(d.all_tags_by_category){ window._lastTags = d.all_tags_by_category; renderVars(); }
        var lastBubble = document.getElementById('chat-msgs').querySelector('.chat-msg.ai:last-child .bubble');
        if(lastBubble){
          var _mhq = highlightMQ(lastBubble.textContent); _mhq = highlightMNPCs(_mhq); lastBubble.innerHTML = _mhq;
          window._allMsgs.push({role:'ai',content:lastBubble.textContent,turn:window._turnCount}); window._msgsShown++;
        }
        if(d.ending_type&&d.ending_type!=='none'){ if(window.showEnding) showEnding(d.ending_type,d.ending_desc||''); }
      }else if(d.type==='hook_effects'){
        if(d.effects&&d.effects.length){
          for(var _n1i=0;_n1i<d.effects.length;_n1i++){
            var _ef2=d.effects[_n1i];
            if(_ef2&&(_ef2.type==='rule_reveal'||_ef2.type==='flash_red'||_ef2.type==='blood_edge')){
              document.body.classList.add('rule-triggered');
              if(window.navigator&&navigator.vibrate) navigator.vibrate(200);
              setTimeout(function(){ document.body.classList.remove('rule-triggered'); },1300);
              break;
            }
          }
          d.effects.sort(function(a,b){return(b.priority||0)-(a.priority||0)});
          (function _iter(idx){ if(idx>=d.effects.length)return; window.renderHookEffect(d.effects[idx].type,d.effects[idx].params||{},function(){_iter(idx+1);}); })(0);
        }
      }else if(d.type==='error'){
        _insertErrorMsg(d.message);
      }else if(d.type==='cancelled'){
        var skEl4 = document.getElementById('chat-msgs').querySelector('.skeleton'); if(skEl4) skEl4.remove();
        window._busy = false;
        document.getElementById('btn-send').style.display = 'flex';
        document.getElementById('btn-stop').style.display = 'none';
        document.getElementById('chat-status').textContent = '已取消';
        showToast('生成已取消','info');
      }
    }else{
      // ──── DESKTOP VERSION ────
      if(d.type==='init_state'||d.type==='turn_complete'){
        var pd = d.player_detail||{}; window._lastPlayerDetail=pd; var cards='',skip=['是否玩家','is_player','外貌','appearance','扩展信息','头像','avatar'];
        var charAvatar=pd['头像']||pd['avatar']||'';
        if(charAvatar&&(charAvatar.indexOf('data:')===0||charAvatar.indexOf('http')===0||charAvatar.indexOf('/static/')===0)){cards+='<div style="text-align:center;margin-bottom:4px"><img class="chat-avatar-sm" src="'+escHTML(charAvatar)+'" style="width:40px;height:40px" onerror="this.remove()"></div>';}
        for(var k in pd){if(!pd.hasOwnProperty(k)||skip.indexOf(k)>=0)continue;var v=pd[k];if(Array.isArray(v))v=v.join(', ');else if(typeof v==='object'&&v!==null)v=JSON.stringify(v).substring(0,50);v=escHTML(String(v));if(v.length>40)v=v.substring(0,40)+'...';cards+='<div class="status-card"><span class="dot"></span><b>'+escHTML(k)+'</b>: '+v+'</div>';}
        document.getElementById('player-cards').innerHTML=cards||'<div class="status-card">无数据</div>';
        document.getElementById('st-tags').textContent=(d.hotTags||[]).length;document.getElementById('st-mems').textContent=(d.hotMemories||[]).length;
        if(d.world_name){document.getElementById('world-name').textContent=d.world_name;document.getElementById('sb-world-name').textContent=d.world_name;document.getElementById('world-desc').textContent=d.world_desc||'--';document.getElementById('sb-world-desc').textContent=d.world_desc||'--';}
        if(d.world_intro){document.getElementById('chat-msgs').innerHTML='<div class="chat-msg-system">'+escHTML(d.world_intro)+'</div>';}
        if(d.type==='init_state'&&(d.opening_monologue||(window._savedMessages||[]).length>0)){
          var saved=window._savedMessages||[];
          if(saved.length>0){
            var chatMsgs=document.getElementById('chat-msgs');chatMsgs.innerHTML='';
            for(var si=0;si<saved.length;si++){
              var sm=saved[si];
              if(sm.role==='user'){chatMsgs.innerHTML+='<div class="chat-msg-user" data-turn="'+(si+1)+'"><img class="chat-avatar" src="'+getPlayerAvatar()+'" onerror="this.remove()"><div class="bubble">'+escHTML(sm.content.replace(/^你: /,''))+'</div></div>';}
              else if(sm.role==='ai'){chatMsgs.innerHTML+='<div class="chat-msg-ai"><img class="chat-avatar" src="'+getAIAvatar()+'" onerror="this.remove()"><div class="bubble">'+highlightQuotes(sm.content)+'</div></div>';}
              else{chatMsgs.innerHTML+='<div class="chat-msg-system">'+escHTML(sm.content)+'</div>';}
            }
            var ums=chatMsgs.querySelectorAll('.chat-msg-user');for(var ui=0;ui<ums.length;ui++)addEditButton(ums[ui]);
            window._savedMessages=null;
          }else{
            document.getElementById('chat-msgs').innerHTML+='<div class="chat-msg-ai"><img class="chat-avatar" src="'+getAIAvatar()+'" onerror="this.remove()"><div class="bubble">'+highlightQuotes(d.opening_monologue)+'</div></div>';
          }
        }
        if(d.type==='init_state'&&d.ai_avatar_url){window._aiAvatar=d.ai_avatar_url;}
        if(d.type==='init_state'&&d.all_tags_by_category){window._lastTagsByCat=d.all_tags_by_category;window._worldBook=d.world_book||[];renderVars();}
        if(d.type==='init_state'){_setupMsgPagination();_initMsgBuffer();}
      }
      if(d.type==='turn_complete'){
        window._turnCount++;
        window._busy=false;setBtns(false);
        var s=document.getElementById('game-status');if(s){s.textContent='OK ['+(d.pass1_tokens||0)+'+'+(d.pass2_tokens||0)+'tk '+(d.latency_ms||0)+'ms]';s.style.color='#4a4';}
        document.getElementById('st-ops').textContent='+'+d.created+' ~'+d.updated+' -'+d.dropped;
        document.getElementById('st-tk').textContent=(d.pass1_tokens||0)+(d.pass2_tokens||0);
        var et=d.ending_type||'none';
        if(et!=='none')showEnding(et,d.ending_desc||'');
        if(d.hook_effects&&Array.isArray(d.hook_effects)){
          for(var _n1i=0;_n1i<d.hook_effects.length;_n1i++){
            var _n1ef=d.hook_effects[_n1i];
            if(_n1ef&&(_n1ef.type==='rule_reveal'||_n1ef.type==='flash_red'||_n1ef.type==='blood_edge')){
              document.body.classList.add('rule-triggered');
              if(window.navigator&&navigator.vibrate)navigator.vibrate(200);
              setTimeout(function(){document.body.classList.remove('rule-triggered');},1300);
              break;
            }
          }
        }
        var msgs=document.getElementById('chat-msgs'),aiBubbles=msgs.querySelectorAll('.chat-msg-ai .bubble');
        for(var bi=aiBubbles.length-1;bi>=0;bi--){
          var raw=aiBubbles[bi].getAttribute('data-raw');
          if(raw){var _hq=highlightQuotes(raw);_hq=highlightNPCs(_hq);aiBubbles[bi].innerHTML=_hq;break;}
        }
        var lastAIBub=msgs.querySelector('.chat-msg-ai:last-child .bubble');
        if(lastAIBub){window._allMsgs.push({role:'ai',content:lastAIBub.textContent,turn:window._turnCount});window._msgsShown++;}
        if(d.all_tags_by_category){window._lastTagsByCat=d.all_tags_by_category;renderVars();}
      }else if(d.type==='narrative_chunk'){
        var msgs=document.getElementById('chat-msgs'),last=msgs.lastElementChild;
        if(!last||!last.classList.contains('chat-msg-ai')){
          last=document.createElement('div');last.className='chat-msg-ai';
          var aiImg=document.createElement('img');aiImg.className='chat-avatar';aiImg.src=getAIAvatar();aiImg.setAttribute('onerror',"this.src='"+_DEF_AVATAR_AI+"'");last.appendChild(aiImg);
          var bubble=document.createElement('div');bubble.className='bubble';last.appendChild(bubble);msgs.appendChild(last);
        }
        var bub=last.querySelector('.bubble');bub.textContent+=d.text;bub.setAttribute('data-raw',bub.textContent);msgs.scrollTop=msgs.scrollHeight;
      }else if(d.type==='hook_effects'){
        if(d.effects&&d.effects.length){
          d.effects.sort(function(a,b){return(b.priority||0)-(a.priority||0)});
          (function _iter(idx){ if(idx>=d.effects.length)return; window.renderHookEffect(d.effects[idx].type,d.effects[idx].params||{},function(){_iter(idx+1);}); })(0);
        }
      }else if(d.type==='error'){window._busy=false;setBtns(false);_insertErrorMsg(d.message);}
      else if(d.type==='cancelled'){window._busy=false;setBtns(false);}
    }
  };

  // ═══ M5: 消息分页 ─────────────────────────────────────────
  var _msgLoadingMore = false;
  window._setupMsgPagination = function _setupMsgPagination(){
    var chatEl = document.getElementById('chat-msgs'); if(!chatEl) return;
    chatEl.addEventListener('scroll',function(){
      if(chatEl.scrollTop<50&&window._allMsgs.length>window._msgsShown&&!_msgLoadingMore) loadMoreMsgs();
    });
  };
  window.scrollChat = function scrollChat(){
    var c = document.getElementById('chat-msgs');
    setTimeout(function(){ if(c) c.scrollTop = c.scrollHeight; }, 50);
  };
  window.loadMoreMsgs = function loadMoreMsgs(){
    if(_msgLoadingMore) return; _msgLoadingMore = true;
    var chatEl = document.getElementById('chat-msgs'); if(!chatEl){ _msgLoadingMore = false; return; }
    var newShown = Math.min(window._allMsgs.length, (window._msgsShown||0) + (window._msgsPageSize||20));
    if(newShown <= (window._msgsShown||0)){ _msgLoadingMore = false; return; }
    var oldH = chatEl.scrollHeight;
    var start = window._allMsgs.length - newShown, end = window._allMsgs.length - (window._msgsShown||0);
    var frag = '';
    for(var i=start;i<end;i++){
      var m = window._allMsgs[i];
      if(window._isMobile){
        if(window.renderMsg) frag += renderMsg(m.role,m.content,m.turn);
      }else{
        if(m.role==='user') frag+='<div class="chat-msg-user" data-turn="'+(m.turn||0)+'"><img class="chat-avatar" src="'+getPlayerAvatar()+'" onerror="this.remove()"><div class="bubble"><b>你:</b> '+escHTML(m.content)+'</div></div>';
        else if(m.role==='ai') frag+='<div class="chat-msg-ai"><img class="chat-avatar" src="'+getAIAvatar()+'" onerror="this.remove()"><div class="bubble">'+highlightQuotes(m.content)+'</div></div>';
        else frag+='<div class="chat-msg-system">'+escHTML(m.content)+'</div>';
      }
    }
    var hint = chatEl.querySelector('.load-more-hint'); if(hint) hint.remove();
    chatEl.insertAdjacentHTML('afterbegin', frag);
    chatEl.scrollTop = chatEl.scrollHeight - oldH;
    window._msgsShown = newShown;
    if(window._msgsShown >= window._allMsgs.length){
      chatEl.insertAdjacentHTML('afterbegin','<div class="load-more-hint" style="color:#888;cursor:default">—— 没有更多消息了 ——</div>');
    }else{
      chatEl.insertAdjacentHTML('afterbegin','<div class="load-more-hint" onclick="loadMoreMsgs()">↑ 加载更早的消息 (剩余'+(window._allMsgs.length-window._msgsShown)+'条)</div>');
    }
    _msgLoadingMore = false;
  };
  window._initMsgBuffer = function _initMsgBuffer(){
    var chatEl = document.getElementById('chat-msgs'); if(!chatEl) return;
    window._allMsgs = [];
    var children = chatEl.children;
    if(window._isMobile){
      for(var i=0;i<children.length;i++){
        var c = children[i];
        if(c.classList.contains('chat-msg')&&c.classList.contains('user')){
          window._allMsgs.push({role:'user',content:c.querySelector('.bubble')?c.querySelector('.bubble').textContent:'',turn:parseInt(c.getAttribute('data-turn'))||0});
        }else if(c.classList.contains('chat-msg')&&c.classList.contains('ai')){
          window._allMsgs.push({role:'ai',content:c.querySelector('.bubble')?c.querySelector('.bubble').textContent:'',turn:0});
        }else if(c.classList.contains('chat-msg')&&c.classList.contains('system')){
          window._allMsgs.push({role:'system',content:c.querySelector('.bubble')?c.querySelector('.bubble').textContent:c.textContent,turn:0});
        }
      }
      if(window._allMsgs.length>(window._msgsPageSize||20)){
        window._msgsShown = window._msgsPageSize||20;
        chatEl.innerHTML = '';
        var start2 = window._allMsgs.length - window._msgsShown;
        for(var j=start2;j<window._allMsgs.length;j++){
          var m2 = window._allMsgs[j];
          if(window.renderMsg) chatEl.innerHTML += renderMsg(m2.role,m2.content,m2.turn);
        }
        chatEl.insertAdjacentHTML('afterbegin','<div class="load-more-hint" onclick="loadMoreMsgs()">↑ 加载更早的消息 ('+(window._allMsgs.length-window._msgsShown)+'条)</div>');
      }else{
        window._msgsShown = window._allMsgs.length;
        chatEl.insertAdjacentHTML('afterbegin','<div class="load-more-hint" style="color:#888;cursor:default">—— 没有更多消息了 ——</div>');
      }
    }else{
      for(var i=0;i<children.length;i++){
        var c = children[i];
        if(c.classList.contains('chat-msg-user')){
          var bub = c.querySelector('.bubble'); var txt = bub?bub.textContent.replace(/^你: /,''):'';
          window._allMsgs.push({role:'user',content:txt,turn:parseInt(c.getAttribute('data-turn'))||0});
        }else if(c.classList.contains('chat-msg-ai')){
          var bub2 = c.querySelector('.bubble');
          window._allMsgs.push({role:'ai',content:bub2?bub2.textContent:'',turn:0});
        }else if(c.classList.contains('chat-msg-system')){
          window._allMsgs.push({role:'system',content:c.textContent,turn:0});
        }
      }
      if(window._allMsgs.length>(window._msgsPageSize||20)){
        window._msgsShown = window._msgsPageSize||20;
        chatEl.innerHTML = '';
        var start2 = window._allMsgs.length - window._msgsShown;
        for(var j=start2;j<window._allMsgs.length;j++){
          var m2 = window._allMsgs[j];
          if(m2.role==='user'){
            var d = document.createElement('div');d.className='chat-msg-user';d.setAttribute('data-turn',m2.turn||0);
            d.innerHTML='<img class="chat-avatar" src="'+getPlayerAvatar()+'" onerror="this.remove()"><div class="bubble"><b>你:</b> '+escHTML(m2.content)+'</div>';
            chatEl.appendChild(d);addEditButton(d);
          }else if(m2.role==='ai'){
            var d2 = document.createElement('div');d2.className='chat-msg-ai';
            d2.innerHTML='<img class="chat-avatar" src="'+getAIAvatar()+'" onerror="this.remove()"><div class="bubble">'+highlightQuotes(m2.content)+'</div>';
            chatEl.appendChild(d2);
          }else{
            var d3 = document.createElement('div');d3.className='chat-msg-system';d3.textContent=m2.content;chatEl.appendChild(d3);
          }
        }
        chatEl.insertAdjacentHTML('afterbegin','<div class="load-more-hint" onclick="loadMoreMsgs()">↑ 加载更早的消息 ('+(window._allMsgs.length-window._msgsShown)+'条)</div>');
      }else{
        window._msgsShown = window._allMsgs.length;
        chatEl.insertAdjacentHTML('afterbegin','<div class="load-more-hint" style="color:#888;cursor:default">—— 没有更多消息了 ——</div>');
      }
    }
    scrollChat();
  };

  // ═══ 消息发送/取消 ─────────────────────────────────────────
  window.sendMsg = function sendMsg(){
    if(window._isMobile){
      // ──── MOBILE VERSION ────
      var inp = document.getElementById('chat-input'), msg = inp.value.trim();
      if(!msg||window._busy) return;
      var ak1 = window._apikey1||window._Stor.getS('apikey1',''); if(!ak1){ showToast('请先设置API Key','error'); return; }
      var ak2 = window._apikey2||window._Stor.getS('apikey2',''); if(!ak2) ak2=ak1;
      if(!window._ws||window._ws.readyState!==WebSocket.OPEN){ connectWS(); setTimeout(function(){sendMsg();},800); return; }
      inp.value=''; inp.style.height='auto'; window._busy = true; window._lastUserInput = msg;
      document.getElementById('btn-send').style.display='none'; document.getElementById('btn-stop').style.display='flex';
      if(window.renderMsg) document.getElementById('chat-msgs').innerHTML += renderMsg('user',msg,window._turnCount);
      scrollChat();
      window._allMsgs.push({role:'user',content:msg,turn:window._turnCount}); window._msgsShown++;
      var m1=window._Stor.getS('model1','deepseek-v4-flash'), m2=window._Stor.getS('model2','deepseek-v4-pro');
      var sk=document.createElement('div');sk.className='skeleton';sk.innerHTML='<div class="sk-avatar"></div><div class="sk-lines"><div class="sk-line"></div><div class="sk-line short"></div></div>';
      document.getElementById('chat-msgs').appendChild(sk); scrollChat();
      window._ws.send(JSON.stringify({type:'user_turn',userInput:msg,apiKey1:ak1,apiKey2:ak2,modelSmall:m1,modelLarge:m2,nValue:window._nValue,myWorldBook:(window._getMyWorldBook?window._getMyWorldBook():[])}));
      showThinking();
    }else{
      // ──── DESKTOP VERSION ────
      var inp=document.getElementById('game-input'),msg=inp.value.trim();
      if(!msg||window._busy)return;
      var ak1=window._apikey1||window._Stor.getS('apikey1','');if(!ak1){showToast('请先在系统设置中填写API Key','error');return}
      var ak2=window._apikey2||window._Stor.getS('apikey2','');if(!ak2)ak2=ak1;
      if(!window._ws||window._ws.readyState!==WebSocket.OPEN){connectWS();setTimeout(function(){sendMsg()},800);return}
      inp.value='';inp.style.height='auto';setBtns(true);window._lastUserInput=msg;
      var div=document.createElement('div');div.className='chat-msg-user';div.setAttribute('data-turn',window._turnCount);
      var img=document.createElement('img');img.className='chat-avatar';img.src=getPlayerAvatar();img.setAttribute('onerror','this.remove()');div.appendChild(img);
      var bub=document.createElement('div');bub.className='bubble';bub.innerHTML='<b>你:</b> '+escHTML(msg);div.appendChild(bub);
      document.getElementById('chat-msgs').appendChild(div);addEditButton(div);
      window._allMsgs.push({role:'user',content:msg,turn:window._turnCount});window._msgsShown++;
      var m1=window._Stor.getS('model1','deepseek-v4-flash'),m2=window._Stor.getS('model2','deepseek-v4-pro');
      window._ws.send(JSON.stringify({type:'user_turn',userInput:msg,apiKey1:ak1,apiKey2:ak2,modelSmall:m1,modelLarge:m2,nValue:window._nValue,myWorldBook:(window._getMyWorldBook?window._getMyWorldBook():[])}));
      showThinking();
    }
  };

  window.cancelMsg = function cancelMsg(){
    if(window._ws&&window._busy) window._ws.send(JSON.stringify({type:'cancel'}));
  };

  // ═══ 存档操作 ─────────────────────────────────────────
  window.doSave = function doSave(){
    if(window._isMobile){
      var msgs=[];document.querySelectorAll('#chat-msgs .chat-msg').forEach(function(c){
        var role=c.classList.contains('user')?'user':(c.classList.contains('ai')?'ai':'system');
        msgs.push({role:role,content:c.querySelector('.bubble')?c.querySelector('.bubble').textContent:c.textContent});
      });
      _fetch('/api/saves',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({slot_name:'存档 '+new Date().toLocaleTimeString(),turn_number:window._turnCount,recent_messages:msgs})}).then(function(d){if(d.ok)showToast('已保存','success');}).catch(function(e){showToast('保存失败: '+e.message,'error');});
    }else{
      var msgs=[];var children=document.getElementById('chat-msgs').children;
      for(var i=0;i<children.length;i++){
        var c=children[i];var role=c.classList.contains('chat-msg-user')?'user':(c.classList.contains('chat-msg-ai')?'ai':'system');
        msgs.push({role:role,content:c.textContent.substring(0,500)});
      }
      _fetch('/api/saves',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({slot_name:'存档 '+new Date().toLocaleTimeString(),turn_number:window._turnCount,recent_messages:msgs})}).then(function(d){if(d.ok){showToast('已保存，共'+d.count+'个存档','success');}else showToast('保存失败','error');}).catch(function(e){showToast('保存失败: '+e.message,'error');});
    }
  };

  window.loadSaves = function loadSaves(){
    if(window._isMobile){
      _fetch('/api/saves').then(function(d){
        var html='';(d.saves||[]).forEach(function(s){
          html+='<div class="list-item" onclick="loadSave('+s.id+')"><div><div class="li-title">'+escHTML(s.slot_name)+'</div><div class="li-sub">回合'+s.turn_number+' · '+escHTML(s.created_at||'')+'</div></div><button class="btn btn-sm btn-outline" onclick="event.stopPropagation();delSave('+s.id+')">删</button></div>';
        });
        document.getElementById('saves-list').innerHTML=html||'<div class="loading">暂无存档</div>';
      }).catch(function(e){showToast('加载存档失败','error');});
    }else{
      _fetch('/api/saves').then(function(d){
        var list=d.saves||[],html='';
        if(!list.length)html='暂无存档';
        else list.forEach(function(s){
          html+='<div style="padding:6px;border-bottom:1px solid #4a3a5a;display:flex;justify-content:space-between;align-items:center"><span>'+escHTML(s.slot_name)+' <small style=color:#888>回合'+s.turn_number+' '+escHTML(s.created_at)+'</small></span><span><button class="btn btn-sm btn-primary" onclick="loadSave('+s.id+')">加载</button> <button class="btn btn-sm btn-secondary" onclick="delSave('+s.id+')">删</button></span></div>';
        });
        document.getElementById('saves-list').innerHTML=html;
      }).catch(function(e){showToast('加载存档失败','error');});
    }
  };

  window.loadSave = function loadSave(id){
    if(window._isMobile){
      showConfirm('加载存档将覆盖当前进度？',function(){
        fetch('/api/saves/'+id,{headers:{'Authorization':'Bearer '+_auth()}}).then(function(r){return r.json()}).then(function(d){
          if(!d.save)return showToast('存档无效','error');
          window._savedMessages=d.save.recent_messages||[];
          fetch('/api/saves/upload',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+_auth()},body:JSON.stringify({slot_name:'loaded',save_data:d.save})}).then(function(){window.navigateTo('pg-chat');});
        });
      });
    }else{
      showConfirm('加载存档将覆盖当前进度，确定吗？',function(){
        showToast('加载存档中...','loading');
        fetch('/api/saves/'+id,{headers:{'Authorization':'Bearer '+_auth()}}).then(function(r){return r.json()}).then(function(d){
          if(d.save){
            window._savedMessages=d.save.recent_messages||[];
            fetch('/api/saves/upload',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+_auth()},body:JSON.stringify({slot_name:'loaded',save_data:d.save})}).then(function(r){return r.json()}).then(function(){
              showToast('存档加载成功','success');window.navTo('page-game');
            }).catch(function(e){showToast('加载失败: '+e.message,'error');});
          }else showToast('存档无效','error');
        }).catch(function(e){showToast('读取失败: '+e.message,'error');});
      });
    }
  };

  window.delSave = function delSave(id){
    if(window._isMobile){
      showConfirm('确定删除此存档？',function(){
        fetch('/api/saves/'+id,{method:'DELETE',headers:{'Authorization':'Bearer '+_auth()}}).then(function(){loadSaves();});
      });
    }else{
      showConfirm('确定删除此存档？',function(){
        window._fetchOk('/api/saves/'+id,{method:'DELETE'},'已删除','删除失败',function(){loadSaves();});
      });
    }
  };

  // ═══ 变量面板渲染 ─────────────────────────────────────────
  window.renderVars = function renderVars(){
    if(window._isMobile){
      var tags=window._lastTags||{},html='',cats={world:'当前副本',map:'地图',rule:'规则',character:'角色',item:'物品'};
      for(var ck in cats){
        var list=tags[ck]||[];if(!list.length)continue;
        html+='<div style="font-weight:700;color:var(--gold);margin:8px 0 4px;font-size:13px">'+cats[ck]+'</div>';
        for(var i=0;i<list.length;i++){
          var t=list[i];
          html+='<div style="padding:6px 8px;margin:2px 0;background:var(--card);border-radius:6px;font-size:12px;border-left:3px solid var(--gold)">'+escHTML(t.tag_name||'')+'<br><span style="color:var(--text2);font-size:11px">'+escHTML((t.tag_hint||'').substring(0,40))+'</span></div>';
        }
	      // World book cards (mobile simplified)
	      var wb=window._worldBook||[];
	      if(wb.length){
	        html+='<div style="font-weight:700;color:var(--accent);margin:8px 0 4px;font-size:13px;border-bottom:1px solid rgba(180,120,180,.3)">📖 世界书</div>';
	        for(var wi=0;wi<wb.length;wi++){
	          var w=wb[wi],wkeys=(w.keys||[]).join(', '),wcontent=w.content||'';
	          html+='<div style="padding:6px 8px;margin:2px 0;background:var(--card);border-radius:6px;font-size:12px;border-left:3px solid '+(w.constant?'#4af':'var(--gold)')+'">'+(w.constant?'🔵':'🟢')+' <span style="color:var(--text2)">['+escHTML(wkeys)+']</span> '+escHTML(wcontent.substring(0,60))+(wcontent.length>60?'...':'')+'</div>';
	        }
	      }
      }
      var el = document.getElementById('vars-content'); if(el) el.innerHTML=html||'暂无变量数据';
    }else{
      // Desktop version — includes character cards with portraits, hearts, relations, spoiler handling, world book cards
      var c=document.getElementById('vars-content'),html='';
      if(!window._lastTagsByCat){c.innerHTML='<p style="font-size:11px;color:#888">等待游戏数据...</p>';return}
      var tags=window._lastTagsByCat||{};
      var cats={world:{label:'世界',icon:'🌍'},map:{label:'地图',icon:'🗺️'},rule:{label:'规则',icon:'📜'},character:{label:'角色',icon:'👤'},item:{label:'物品',icon:'🎒'},memory:{label:'记忆',icon:'💭'}};
      var charIndex=0;
      var _varsCollapsed = window._varsCollapsed||{};
      var _spoilerOn = window._spoilerOn||false;
      function isSpoilerField(key){
        return key.startsWith('隐藏')||key.startsWith('_')||['真实规则','隐藏真相','隐藏区域','隐藏效果','真实身份'].indexOf(key)>=0;
      }
      for(var ck in cats){
        var cat=cats[ck],list=tags[ck]||[];if(!list.length)continue;
        var collapsed=_varsCollapsed[ck]||false;
        html+='<h3 style="cursor:pointer;display:flex;align-items:center;gap:4px" onclick="window._toggleVarCat(\''+ck+'\')"><span style="font-size:10px">'+(collapsed?'▶':'▼')+'</span> '+cat.icon+' '+cat.label+' <small style="color:#888;font-weight:400">('+list.length+')</small></h3>';
        html+='<div class="vars-cat-body" id="vcat-'+ck+'" style="'+(collapsed?'display:none':'')+'">';
        for(var i=0;i<list.length;i++){
          var t=list[i],name=t.tag_name||'',hint=t.tag_hint||'',detail=t.tag_detail||{},isSpoiler=false,spoilerKeys=[];
          for(var k in detail){if(detail.hasOwnProperty(k)&&isSpoilerField(k)){isSpoiler=true;spoilerKeys.push(k)}}
          var cls='v-item'+(isSpoiler?' spoiler':'')+(_spoilerOn&&isSpoiler?' visible':'');
          if(ck==='character'&&!detail['是否玩家']){
            var portrait=detail['立绘']||detail['立绘表情']||'';
            if(portrait&&typeof portrait==='object')portrait=portrait['默认']||Object.values(portrait)[0]||'';
            var theme=detail['主题色']||'#d4708a';
            var charTags=detail['角色标签']||[];
            var rels=detail['对其他角色的态度']||{};
            var att=detail['对玩家的态度']||{};var fav=parseInt(att['好感度'])||0,trust=parseInt(att['信任度'])||0;
            html+='<div class="'+cls+' char-card" style="border-left:3px solid '+theme+';margin:4px 0;padding:6px 8px;background:rgba(255,255,255,.04);border-radius:0 6px 6px 0;box-shadow:0 0 10px '+theme+'44,0 0 20px '+theme+'18">';
            html+='<div style="display:flex;align-items:center;gap:5px">';
            if(portrait)html+='<img class="char-portrait" src="'+escHTML(portrait)+'" onerror="this.remove()" style="width:32px;height:32px;border-radius:50%;border:2px solid '+theme+';object-fit:cover;flex-shrink:0;box-shadow:0 0 10px '+theme+'66">';
            html+='<div style="flex:1;min-width:0"><b style="font-size:11px;color:'+theme+'">'+escHTML(name)+'</b>';
            if(charTags.length)html+='<br><span style="font-size:9px;color:#888">'+escHTML(charTags.join(' · '))+'</span>';
            html+='</div></div>';
            var favHearts='';
            if(fav>0){var heartCount=Math.min(Math.ceil(fav/20),5);for(var hi=0;hi<heartCount;hi++)favHearts+='❤';for(var he=heartCount;he<5;he++)favHearts+='♡';}
            else{favHearts='♡♡♡♡♡';}
            html+='<div style="font-size:10px;margin-top:3px;color:'+theme+';opacity:.85">'+favHearts+'</div>';
            if(_spoilerOn&&(att['好感度']!=null||att['信任度']!=null)){
              html+='<div style="font-size:9px;margin-top:2px;color:#888">';
              if(att['好感度']!=null)html+='好感 '+att['好感度']+'/100 ';
              if(att['信任度']!=null)html+='信任 '+att['信任度']+'/100';
              html+='</div>';
            }
            var relKeys=Object.keys(rels);
            if(relKeys.length){
              html+='<div style="font-size:9px;color:#888;margin-top:2px">';
              for(var ri=0;ri<Math.min(relKeys.length,3);ri++){
                var rk=relKeys[ri],rv=rels[rk];if(typeof rv==='string'&&rv.length>20)rv=rv.substring(0,20)+'...';
                html+='→ '+escHTML(rk)+': <span style="color:var(--ink-light)">'+escHTML(String(rv))+'</span> ';
              }
              html+='</div>';
            }
            html+='</div>';
            charIndex++;
          }else{
            html+='<div class="'+cls+'" title="'+escHTML(hint)+'">'+escHTML(name);
            if(isSpoiler&&_spoilerOn){for(var si=0;si<spoilerKeys.length;si++){var sk=spoilerKeys[si],sv=String(detail[sk]||'').substring(0,30);html+='<br><small style="color:var(--blood)">'+escHTML(sk)+': '+escHTML(sv)+'</small>';}}
            html+='</div>';
          }
        }
        html+='</div>';
      }
      // World book cards
      var wb=window._worldBook||[];
      if(wb.length){
        html+='<h3 style="font-size:11px;color:var(--blood);margin:8px 0 4px;border-bottom:1px solid rgba(180,120,180,.3)">📖 世界书</h3>';
        for(var wi=0;wi<wb.length;wi++){
          var w=wb[wi],wkeys=(w.keys||[]).join(', '),wcontent=w.content||'';
          var triggered=window._wbTriggered&&window._wbTriggered[wi];
          html+='<div class="wb-card'+(triggered?' triggered':'')+(window._wbExpanded&&window._wbExpanded[wi]?' expanded':'')+'" onclick="window._toggleWbCard('+wi+')"><div class="wb-card-header"><span class="wb-keyword-tag'+(w.constant?' constant':'')+'">'+(w.constant?'🔵':'🟢')+' '+escHTML(wkeys)+'</span></div><div class="wb-summary">'+escHTML(wcontent.substring(0,60))+(wcontent.length>60?'...':'')+'</div><div class="wb-full">'+escHTML(wcontent)+'</div></div>';
        }
      }
      // Player card
      var pd=window._lastPlayerDetail||{};
      if(Object.keys(pd).length){
        html+='<h3 style="font-size:11px;color:var(--blood);margin:8px 0 4px;border-bottom:1px solid rgba(180,120,180,.3)">👤 玩家状态</h3>';
        html+='<div class="status-card" style="background:rgba(139,32,32,.06)">';
        var hp=pd['血量']||pd['生命值']||pd['HP']||pd['hp']||'?',maxHp=pd['最大血量']||pd['最大生命值']||pd['max_hp']||hp;
        var san=pd['理智']||pd['理智值']||pd['SAN']||pd['sanity']||'?',maxSan=pd['最大理智']||pd['最大理智值']||pd['max_sanity']||san;
        html+='❤️ HP: '+hp+'/'+maxHp+' | 🧠 SAN: '+san+'/'+maxSan;
        html+='</div>';
      }
      c.innerHTML=html||'<p style="font-size:11px;color:#888">暂无变量数据</p>';
    }
  };

  // Desktop helper: toggle variable category collapse
  window._toggleVarCat = function(ck){
    window._varsCollapsed = window._varsCollapsed||{};
    window._varsCollapsed[ck] = !window._varsCollapsed[ck];
    renderVars();
  };
  // Desktop helper: toggle world book card expand
  window._toggleWbCard = function(idx){
    window._wbExpanded = window._wbExpanded||{};
    window._wbExpanded[idx] = !window._wbExpanded[idx];
    renderVars();
  };

})();

// ═══ Unified Hook Effect Rendering (shared by desktop + mobile) ═══════════════════════════════
window._activeHookTimers = [];

function _hookTarget() {
  return document.getElementById(window._isMobile ? 'app' : 'game-chat');
}

function _hookSchedule(fn, ms) {
  var id = setTimeout(fn, ms);
  window._activeHookTimers.push(id);
  return id;
}

function clearAllHookEffects() {
  window._activeHookTimers.forEach(function(t) { clearTimeout(t); });
  window._activeHookTimers = [];
  document.querySelectorAll('.hook-popup-overlay,.hook-fullscreen-text,.hook-chapter-title,.hook-scene-transition,.input-lock-overlay,.fav-float,.degrade-notice,.particle').forEach(function(e) { e.remove(); });
  var target = _hookTarget();
  if (target) {
    target.classList.remove('hook-flash-red','hook-screen-shake','hook-golden-glow','hook-vignette-pulse','hook-blood-edge','hook-heartbeat-warm','hook-glitch-text','hook-breathing');
    target.style.boxShadow = '';
    target.style.filter = '';
    target.style.transform = '';
    target.style.borderColor = '';
    target.style.background = '';
  }
  document.body.style.filter = '';
}

// ── P0 core effects (unified) ──

function _eff_flash_red(p, next) {
  var target = _hookTarget();
  if (!target) { next(); return; }
  var cnt = parseInt(p.count) || 3, dur = (parseFloat(p.duration) || 0.5) * 1000;
  target.classList.add('hook-flash-red');
  _hookSchedule(function() { target.classList.remove('hook-flash-red'); next(); }, dur * cnt + 100);
}

function _eff_screen_shake(p, next) {
  var target = _hookTarget();
  if (!target) { next(); return; }
  var map = {light:300, medium:500, heavy:800};
  var dur = map[p.intensity] || 500;
  target.classList.add('hook-screen-shake');
  _hookSchedule(function() { target.classList.remove('hook-screen-shake'); next(); }, dur + 100);
}

function _eff_golden_glow(p, next) {
  var target = _hookTarget();
  if (!target) { next(); return; }
  var dur = (parseFloat(p.duration) || 3) * 1000;
  target.classList.add('hook-golden-glow');
  _hookSchedule(function() { target.classList.remove('hook-golden-glow'); next(); }, dur + 100);
}

function _eff_vignette_pulse(p, next) {
  var target = _hookTarget();
  if (!target) { next(); return; }
  var dur = (parseFloat(p.duration) || 3) * 1000;
  target.classList.add('hook-vignette-pulse');
  _hookSchedule(function() { target.classList.remove('hook-vignette-pulse'); next(); }, dur + 100);
}

function _eff_blood_edge(p, next) {
  var target = _hookTarget();
  if (!target) { next(); return; }
  var dur = (parseFloat(p.duration) || 3) * 1000;
  target.classList.add('hook-blood-edge');
  _hookSchedule(function() { target.classList.remove('hook-blood-edge'); next(); }, dur + 100);
}

function _eff_heartbeat_warm(p, next) {
  if (window._isMobile) {
    _eff_golden_glow(p, next);
    return;
  }
  var target = _hookTarget();
  if (!target) { next(); return; }
  var dur = (parseFloat(p.duration) || 5) * 1000;
  target.classList.add('hook-heartbeat-warm');
  _hookSchedule(function() { target.classList.remove('hook-heartbeat-warm'); next(); }, dur + 100);
}

function _eff_breathing(p, next) {
  if (window._isMobile) {
    var dur = (parseFloat(p.duration) || 4) * 1000;
    _hookSchedule(next, dur);
    return;
  }
  var target = _hookTarget();
  if (!target) { next(); return; }
  var dur = (parseFloat(p.duration) || 4) * 1000;
  target.classList.add('hook-breathing');
  _hookSchedule(function() { target.classList.remove('hook-breathing'); next(); }, dur + 100);
}

function _eff_glitch_text(p, next) {
  if (window._isMobile) {
    var target = _hookTarget();
    if (!target) { next(); return; }
    var dur = (parseFloat(p.duration) || 2) * 1000;
    target.style.filter = 'hue-rotate(90deg)';
    _hookSchedule(function() { target.style.filter = ''; next(); }, dur + 100);
    return;
  }
  var target = _hookTarget();
  if (!target) { next(); return; }
  var dur = (parseFloat(p.duration) || 2) * 1000;
  target.classList.add('hook-glitch-text');
  _hookSchedule(function() { target.classList.remove('hook-glitch-text'); next(); }, dur + 100);
}

// ═══ Comfort settings (unified) ═══════════════════════════════
window.getComfort = function getComfort() {
  try { return JSON.parse(localStorage.getItem('mvp_comfort') || '{"flash":true,"audio":true,"distort":true,"jumpscare":true,"lock":true}'); }
  catch(e) { return {flash:true,audio:true,distort:true,jumpscare:true,lock:true}; }
};
window.setComfort = function setComfort(c) { localStorage.setItem('mvp_comfort', JSON.stringify(c)); };
window.shouldPlay = function shouldPlay(effectType) {
  var c = window.getComfort();
  if (['flash_red','screen_shake','glitch_text','vignette_pulse'].indexOf(effectType) >= 0) return c.flash !== false;
  if (['sound_fx','bg_music','sudden_silence','heartbeat_warm','music_box'].indexOf(effectType) >= 0) return c.audio !== false;
  if (['screen_blur','blood_edge','color_tone','breathing'].indexOf(effectType) >= 0) return c.distort !== false;
  if (['portrait_popup','clue_image','scene_illustration','note_card','ending_card','binary_choice','fullscreen_text_popup','diary_flip','scene_transition'].indexOf(effectType) >= 0) return c.jumpscare !== false;
  if (effectType === 'input_lock') return c.lock !== false;
  return true;
};
window.degradeNotice = function degradeNotice(desc) {
  var el = document.createElement('div'); el.className = 'degrade-notice';
  el.textContent = '⚠ 恐怖效果已关闭：' + desc;
  document.body.appendChild(el);
  setTimeout(function() { el.remove(); }, 3000);
};

// ═══ Helpers for DOM differences ═══════════════════════════════
function _msgTarget() { return document.getElementById('chat-msgs'); }
function _statusTarget() { return document.getElementById(window._isMobile ? 'chat-status' : 'game-status'); }
function _inputTarget() { return document.getElementById(window._isMobile ? 'chat-input' : 'game-input'); }
function _sendBtn() { return document.getElementById('btn-send'); }
function _navHome() { if (window._isMobile) window.navigateTo('pg-home'); else window.navTo('page-home'); }

// Append a system message. If isHTML is falsey, use textContent (desktop) / bubble textContent (mobile).
// If isHTML is truthy, use innerHTML.
function _appendSysMsg(text, isHTML) {
  var msgs = _msgTarget(); if (!msgs) return null;
  var div = document.createElement('div');
  if (window._isMobile) {
    div.className = 'chat-msg system';
    var bub = document.createElement('div'); bub.className = 'bubble';
    if (isHTML) bub.innerHTML = text; else bub.textContent = text;
    div.appendChild(bub);
  } else {
    div.className = 'chat-msg-system';
    if (isHTML) div.innerHTML = text; else div.textContent = text;
  }
  msgs.appendChild(div);
  scrollChat();
  return div;
}

// Append a system message and return the text node/element for typewriter effects
function _appendSysMsgForTypewriter() {
  var msgs = _msgTarget(); if (!msgs) return null;
  if (window._isMobile) {
    var div = document.createElement('div'); div.className = 'chat-msg system';
    var bub = document.createElement('div'); bub.className = 'bubble';
    div.appendChild(bub); msgs.appendChild(div); scrollChat();
    return {el: div, textEl: bub};
  } else {
    var div = document.createElement('div'); div.className = 'chat-msg-system';
    msgs.appendChild(div); scrollChat();
    return {el: div, textEl: div};
  }
}

// ═══ P1: Visual effects ═══════════════════════════════

function _eff_portrait_popup(p, next) {
  var ov = document.createElement('div'); ov.className = 'hook-popup-overlay';
  var escFn = window.escHTML;
  var btnId = window._isMobile ? '_mppclose' : '_ppclose';
  ov.innerHTML = '<div class="hook-portrait-popup">' +
    (p.image_url ? '<img src="' + escFn(p.image_url) + '" onerror="this.style.display=\'none\'">' : '') +
    '<div class="npc-line">' + (p.npc_name ? '<b>' + escFn(p.npc_name) + '</b>: ' : '') + escFn(p.line || '') + '</div>' +
    '<button class="btn btn-primary btn-sm" id="' + btnId + '">继续</button></div>';
  document.body.appendChild(ov);
  ov.querySelector('#' + btnId).onclick = function() { ov.remove(); next(); };
  ov.onclick = function(e) { if (e.target === ov) { ov.remove(); next(); } };
}

function _eff_ending_card(p, next) {
  var ov = document.createElement('div'); ov.className = 'hook-popup-overlay'; ov.style.zIndex = '300';
  var escFn = window.escHTML;
  var btnId = window._isMobile ? '_mendok' : '_endok';
  ov.innerHTML = '<div class="hook-ending-card"><div class="end-icon">' + (p.icon || '🌕') + '</div>' +
    '<div class="end-title">' + escFn(p.title || '结局') + '</div>' +
    '<div class="end-desc">' + escFn(p.desc || '') + '</div>' +
    '<button class="btn btn-primary" id="' + btnId + '">返回主菜单</button></div>';
  document.body.appendChild(ov);
  ov.querySelector('#' + btnId).onclick = function() { ov.remove(); _navHome(); };
}

function _eff_clue_image(p, next) {
  var ov = document.createElement('div'); ov.className = 'hook-popup-overlay';
  var escFn = window.escHTML;
  var btnId = window._isMobile ? '_mclclose' : '_clclose';
  ov.innerHTML = '<div class="hook-clue-image"><img src="' + escFn(p.image_url || '') + '" onerror="this.parentElement.innerHTML=\'<div style=color:var(--blood);padding:20px>图片加载失败</div>\'"><div class="caption">' + escFn(p.caption || '') + '</div><button class="btn btn-primary btn-sm" id="' + btnId + '" style="margin-top:10px">关闭</button></div>';
  document.body.appendChild(ov);
  ov.querySelector('#' + btnId).onclick = function() { ov.remove(); next(); };
  ov.onclick = function(e) { if (e.target === ov) { ov.remove(); next(); } };
}

function _eff_note_card(p, next) {
  var ov = document.createElement('div'); ov.className = 'hook-popup-overlay';
  var escFn = window.escHTML;
  var style = p.style || 'parchment';
  var btnId = window._isMobile ? '_mncclose' : '_ncclose';
  var btnHtml = window._isMobile
    ? '<button class="btn btn-sm btn-outline" id="' + btnId + '" style="margin-top:8px">关闭</button>'
    : '<button class="btn btn-sm" style="margin-top:8px;background:#888;color:#fff" id="' + btnId + '">关闭</button>';
  var maxH = window._isMobile ? '150px' : '200px';
  ov.innerHTML = '<div class="hook-note-card ' + style + '"><h3>' + escFn(p.title || '') + '</h3>' +
    (p.image ? '<img src="' + escFn(p.image) + '" style="max-width:100%;max-height:' + maxH + ';object-fit:contain;margin:6px 0;border-radius:4px" onerror="this.remove()">' : '') +
    '<p>' + escFn(p.content || '') + '</p>' + btnHtml + '</div>';
  document.body.appendChild(ov);
  ov.querySelector('#' + btnId).onclick = function() { ov.remove(); next(); };
  ov.onclick = function(e) { if (e.target === ov) { ov.remove(); next(); } };
}

function _eff_typewriter(p, next) {
  var res = _appendSysMsgForTypewriter(); if (!res) { next(); return; }
  var text = p.text || '', i = 0, textEl = res.textEl;
  function type() {
    if (i < text.length) { textEl.textContent += text.charAt(i); i++; _hookSchedule(type, 40 + Math.random() * 60); }
    else { next(); }
  }
  type();
}

function _eff_fullscreen_text(p, next) {
  var ov = document.createElement('div'); ov.className = 'hook-fullscreen-text ' + (p.style || 'normal');
  ov.textContent = p.text || '';
  document.body.appendChild(ov);
  _hookSchedule(function() { ov.remove(); next(); }, 2500);
}

function _eff_chapter_title(p, next) {
  var msgs = _msgTarget(); if (!msgs) { next(); return; }
  var div = document.createElement('div'); div.className = 'hook-chapter-title';
  var escFn = window.escHTML;
  var subSize = window._isMobile ? '12px' : '14px';
  div.innerHTML = escFn(p.text || '') + (p.subtitle ? '<br><small style="font-size:' + subSize + ';color:var(--ink-light);font-weight:400">' + escFn(p.subtitle) + '</small>' : '');
  msgs.appendChild(div); scrollChat();
  _hookSchedule(function() { div.style.opacity = '0'; div.style.transition = 'opacity 1s'; setTimeout(function() { div.remove(); next(); }, 1000); }, 2000);
}

function _eff_scene_transition(p, next) {
  var msgs = _msgTarget(); if (!msgs) { next(); return; }
  var div = document.createElement('div'); div.className = 'hook-scene-transition';
  div.textContent = p.text || '';
  msgs.appendChild(div); scrollChat();
  _hookSchedule(function() { div.remove(); next(); }, 2500);
}

function _eff_diary_flip(p, next) {
  var ov = document.createElement('div'); ov.className = 'hook-popup-overlay'; ov.style.zIndex = '270';
  var escFn = window.escHTML;
  var btnId = window._isMobile ? '_mdfclose' : '_dfclose';
  var btnHtml = window._isMobile
    ? '<button class="btn btn-sm btn-outline" id="' + btnId + '">关闭</button>'
    : '<button class="btn btn-sm" style="margin-top:8px;background:#888;color:#fff" id="' + btnId + '">关闭</button>';
  var maxH = window._isMobile ? '150px' : '200px';
  ov.innerHTML = '<div class="hook-note-card diary"><h3>' + escFn(p.title || '') + '</h3>' +
    (p.image ? '<img src="' + escFn(p.image) + '" style="max-width:100%;max-height:' + maxH + ';object-fit:contain;margin:6px 0;border-radius:4px" onerror="this.remove()">' : '') +
    '<p>' + escFn(p.content || '') + '</p>' + btnHtml + '</div>';
  document.body.appendChild(ov);
  ov.querySelector('#' + btnId).onclick = function() { ov.remove(); next(); };
  ov.onclick = function(e) { if (e.target === ov) { ov.remove(); next(); } };
}

function _eff_warm_flashback(p, next) {
  var ov = document.createElement('div'); ov.className = 'hook-fullscreen-text gold';
  ov.style.opacity = window._isMobile ? '0.7' : '0.8';
  ov.textContent = p.text || '';
  document.body.appendChild(ov);
  _hookSchedule(function() { ov.remove(); next(); }, 3000);
}

function _eff_fullscreen_text_popup(p, next) {
  var ov = document.createElement('div'); ov.className = 'hook-popup-overlay';
  var escFn = window.escHTML;
  var smallSize = window._isMobile ? '11px' : '12px';
  var extraStyle = window._isMobile ? 'font-size:20px' : '';
  ov.innerHTML = '<div class="hook-fullscreen-text ' + (p.style || 'normal') + '" style="position:relative;cursor:pointer;' + extraStyle + '">' + escFn(p.text || '') + '<br><small style="font-size:' + smallSize + ';color:#888;font-weight:400">点击关闭</small></div>';
  document.body.appendChild(ov);
  ov.onclick = function() { ov.remove(); next(); };
}

function _eff_sunlight(p, next) {
  var target = window._isMobile ? document.getElementById('app') : document.getElementById('game-chat');
  if (!target) { next(); return; }
  target.style.background = 'linear-gradient(180deg,rgba(255,240,200,.1),transparent)';
  _hookSchedule(function() { target.style.background = ''; next(); }, 5000);
}

function _eff_color_tone(p, next) {
  var tones = {cold: 'sepia(0.3) hue-rotate(180deg)', warm: 'sepia(0.3) saturate(1.2)', red: 'sepia(0.5) hue-rotate(-30deg)', desaturated: 'grayscale(0.5)'};
  document.body.style.filter = tones[p.tone] || '';
  _hookSchedule(function() { document.body.style.filter = ''; next(); }, 4000);
}

function _eff_petal_fall(p, next) {
  var isMobile = window._isMobile;
  var colors = {
    sakura: isMobile ? ['#ffb7c5','#ffc0cb'] : ['#ffb7c5','#ffc0cb','#ffd1dc'],
    light: isMobile ? ['#ffe4b5','#fff8dc'] : ['#ffe4b5','#fff8dc','#ffefd5'],
    gold: isMobile ? ['#ffd700','#ffec8b'] : ['#ffd700','#ffec8b','#daa520']
  };
  var c = colors[p.style] || colors.sakura;
  var count = isMobile ? 12 : 20;
  for (var i = 0; i < count; i++) {
    var pt = document.createElement('div'); pt.className = 'particle';
    pt.style.left = Math.random() * 100 + '%';
    pt.style.top = isMobile ? '-10px' : '-20px';
    pt.style.width = (isMobile ? (5 + Math.random() * 6) : (6 + Math.random() * 8)) + 'px';
    pt.style.height = pt.style.width;
    pt.style.background = c[Math.floor(Math.random() * c.length)];
    pt.style.borderRadius = '50%';
    pt.style.animationDuration = (3 + Math.random() * 3) + 's';
    if (!isMobile) pt.style.animationDelay = Math.random() * 2 + 's';
    document.body.appendChild(pt);
    _hookSchedule(function() { pt.remove(); }, 6000);
  }
  next();
}

// ═══ P1: NPC / Character effects ═══════════════════════════════

function _eff_npc_chat(p, next) {
  var msgs = _msgTarget(); if (!msgs) { next(); return; }
  var npcName = p.npc_name || '???', content = p.line || p.content || '';
  var div = document.createElement('div');
  if (window._isMobile) {
    div.className = 'chat-msg ai';
    div.innerHTML = '<div class="avatar">' + escHTML(npcName.charAt(0)) + '</div><div class="bubble"><b>' + escHTML(npcName) + ':</b> ' + escHTML(content) + '</div>';
  } else {
    div.className = 'chat-msg-ai';
    div.innerHTML = '<img class="chat-avatar" src="data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="48" fill="#8a6090"/><text x="50" y="60" text-anchor="middle" fill="#fce8d0" font-size="20">' + escHTML(npcName.charAt(0)) + '</text></svg>') + '" onerror="this.remove()"><div class="bubble"><b>' + escHTML(npcName) + ':</b> ' + escHTML(content) + '</div>';
  }
  msgs.appendChild(div); scrollChat();
  _hookSchedule(next, window._isMobile ? 400 : 500);
}

function _eff_npc_enter(p, next) {
  var text = '✨ ' + escHTML(p.npc_name || 'NPC') + '登场' + (p.line ? '：' + escHTML(p.line) : '');
  _appendSysMsg(text, true);
  next();
}

function _eff_npc_exit(p, next) {
  var text = '💫 ' + escHTML(p.npc_name || 'NPC') + '退场';
  _appendSysMsg(text, true);
  next();
}

function _eff_fav_animation(p, next) {
  var npc = p.npc_name || 'NPC', amount = p.amount || '+0';
  var el = document.createElement('div'); el.className = 'fav-float';
  el.textContent = npc + ' ' + (amount.indexOf('+') >= 0 || parseInt(amount) > 0 ? '❤' : '💔') + ' ' + amount;
  el.style.left = (window._isMobile ? (30 + Math.random() * 50) : (40 + Math.random() * 40)) + '%';
  el.style.top = window._isMobile ? '45%' : '50%';
  el.style.color = amount.indexOf('+') >= 0 || parseInt(amount) > 0 ? '#ff6b8a' : '#888';
  document.body.appendChild(el);
  _hookSchedule(function() { el.remove(); next(); }, 2000);
}

function _eff_dialogue_bubble(p, next) { _eff_npc_chat(p, next); }
function _eff_npc_comfort(p, next) { _eff_portrait_popup(p, next); }
function _eff_scene_illustration(p, next) { _eff_clue_image({image_url: p.image_url, caption: p.caption || ''}, next); }
function _eff_expression_change(p, next) { next(); }

// ═══ P1: Game mechanics ═══════════════════════════════

function _eff_binary_choice(p, next) {
  var ov = document.createElement('div'); ov.className = 'hook-popup-overlay'; ov.style.zIndex = '280';
  var escFn = window.escHTML;
  var btnBClass = window._isMobile ? 'btn btn-outline' : 'btn btn-secondary';
  ov.innerHTML = '<div class="hook-binary-choice"><h3 style="color:var(--blood);margin-bottom:10px">做出选择</h3><div class="bc-btns"><button class="btn btn-primary" id="_bcA">' + escFn(p.option_a || '选项A') + '</button><button class="' + btnBClass + '" id="_bcB">' + escFn(p.option_b || '选项B') + '</button></div></div>';
  document.body.appendChild(ov);
  function choose(result) {
    ov.remove();
    if (result) _appendSysMsg(result, false);
    next();
  }
  ov.querySelector('#_bcA').onclick = function() { choose(p.result_a); };
  ov.querySelector('#_bcB').onclick = function() { choose(p.result_b); };
}

function _eff_input_lock(p, next) {
  var isMobile = window._isMobile;
  var target = isMobile ? document.getElementById('app') : document.getElementById('game-chat');
  if (!target) { next(); return; }
  var text = p.text || '你被恐惧攘住，无法行动...';
  var timeoutSec = Math.min(parseInt(p.timeout_seconds) || 10, 15);
  var kw = p.unlock_keyword || '';
  var inp = _inputTarget(), sendBtn = _sendBtn();
  var ov = document.createElement('div');
  ov.className = 'input-lock-overlay';
  ov.id = isMobile ? 'm-input-lock-el' : 'input-lock-el';
  var xBtnId = isMobile ? 'mlock-x-btn' : 'lock-x-btn';
  var timerId = isMobile ? 'mlock-timer' : 'lock-timer';
  var kwInputId = isMobile ? 'mlock-kw-input' : 'lock-kw-input';
  ov.innerHTML = '<button class="lock-close" id="' + xBtnId + '">×</button><div class="lock-text">' + escHTML(text) + '</div><div class="lock-timer" id="' + timerId + '">' + timeoutSec + 's</div>';
  if (p.unlock_method === 'input' && kw) ov.innerHTML += '<input type="text" class="lock-keyword-input" id="' + kwInputId + '" placeholder="输入关键字解锁...">';
  if (isMobile) {
    var inputBar = target.querySelector('.input-bar');
    if (inputBar) inputBar.style.position = 'relative';
  }
  target.appendChild(ov);
  if (inp) inp.disabled = true; if (sendBtn) sendBtn.disabled = true;
  var remaining = timeoutSec, unlocked = false;
  function doUnlock() {
    if (unlocked) return; unlocked = true;
    var el = document.getElementById(isMobile ? 'm-input-lock-el' : 'input-lock-el');
    if (el) el.remove();
    if (inp) inp.disabled = false; if (sendBtn) sendBtn.disabled = false;
    next();
  }
  var timer = setInterval(function() {
    remaining--;
    var tel = document.getElementById(timerId); if (tel) tel.textContent = remaining + 's';
    if (remaining <= 0) { clearInterval(timer); doUnlock(); }
  }, 1000);
  window._activeHookTimers.push(timer);
  var safetyTimer = setTimeout(function() { clearInterval(timer); doUnlock(); }, timeoutSec * 1000 + 500);
  window._activeHookTimers.push(safetyTimer);
  var xBtn = ov.querySelector('#' + xBtnId);
  if (xBtn) xBtn.onclick = function() { clearInterval(timer); clearTimeout(safetyTimer); doUnlock(); };
  var kwInput = ov.querySelector('#' + kwInputId);
  if (kwInput) {
    kwInput.onkeydown = function(e) {
      if (e.key === 'Enter') {
        if (kwInput.value.trim() === kw) { clearInterval(timer); clearTimeout(safetyTimer); doUnlock(); }
        else { kwInput.value = ''; kwInput.placeholder = '错误，请重试'; }
      }
    };
  }
}

function _eff_reveal_tag(p, next) {
  var tagName = p.tag_name || '';
  if (tagName) _appendSysMsg('🏷 揭示标签：' + escHTML(tagName), true);
  next();
}

function _eff_rule_reveal(p, next) {
  var text = '📜 <b>规则揭示：' + escHTML(p.rule_name || '') + '</b><br>' + escHTML(p.rule_text || '');
  _appendSysMsg(text, true);
  next();
}

function _eff_give_item(p, next) {
  var text = '🎁 获得物品：' + escHTML(p.item_name || '') + (p.item_desc ? ' - ' + escHTML(p.item_desc) : '');
  _appendSysMsg(text, true);
  next();
}

function _eff_attr_change(p, next) {
  var field = p.field === 'sanity' ? '理智值' : '血量';
  var text = (parseInt(p.amount) > 0 ? '✨' : '💢') + ' ' + field + ' ' + (parseInt(p.amount) > 0 ? '+' : '') + (p.amount || '0');
  _appendSysMsg(text, true);
  next();
}

function _eff_point_reward(p, next) {
  _appendSysMsg('⭐ 积分 +' + (p.amount || 0), true);
  next();
}

function _eff_local_flag(p, next) { next(); }

// ═══ P1: Environment / Atmosphere effects ═══════════════════════════════

function _eff_screen_blur(p, next) {
  var target = _hookTarget(); if (!target) { next(); return; }
  var isMobile = window._isMobile;
  var dur = (parseFloat(p.duration) || 2) * 1000;
  target.style.filter = 'blur(' + (p.intensity === 'heavy' ? (isMobile ? '2px' : '4px') : (isMobile ? '2px' : '2px')) + ')';
  _hookSchedule(function() { target.style.filter = ''; next(); }, dur + 100);
}

function _eff_border_color(p, next) {
  var target = _hookTarget(); if (!target) { next(); return; }
  var isMobile = window._isMobile;
  var color = p.color || '#b84a5c', dur = (parseFloat(p.duration) || 3) * 1000;
  target.style.borderColor = color;
  target.style.boxShadow = '0 0 ' + (isMobile ? '15px' : '20px') + ' ' + color + '44';
  _hookSchedule(function() { target.style.borderColor = ''; target.style.boxShadow = ''; next(); }, dur);
}

function _eff_chat_bg(p, next) {
  var target = _hookTarget(); if (!target) { next(); return; }
  var dur = (parseFloat(p.duration) || 5) * 1000;
  if (p.image_url) target.style.background = 'url(' + escHTML(p.image_url) + ') center/cover';
  _hookSchedule(function() { if (p.image_url) target.style.background = ''; next(); }, dur);
}

function _eff_status_flash(p, next) {
  var st = _statusTarget(); if (!st) { next(); return; }
  var dur = (parseFloat(p.duration) || 2) * 1000;
  if (window._isMobile) {
    st.style.animation = 'fadeIn .3s ease alternate 6';
  } else {
    var color = p.color || 'rgba(180,74,92,.3)';
    document.documentElement.style.setProperty('--flash-color', color);
    st.style.animation = 'statusFlash ' + dur + 'ms ease-in-out';
  }
  _hookSchedule(function() { st.style.animation = ''; next(); }, dur + 100);
}

function _eff_music_box(p, next) {
  var target = _hookTarget(); if (!target) { next(); return; }
  target.style.filter = window._isMobile ? 'brightness(1.08)' : 'brightness(1.1)';
  _hookSchedule(function() { target.style.filter = ''; next(); }, 4000);
}

function _eff_sudden_silence(p, next) {
  var dur = (parseFloat(p.duration) || 2) * 1000;
  _hookSchedule(next, dur);
}

function _eff_button_morph(p, next) { next(); }
function _eff_bg_music(p, next) { next(); }
function _eff_sound_fx(p, next) { next(); }

function _eff_particles(p, next) {
  var isMobile = window._isMobile;
  var colors = {rain: '#aaccff', snow: '#ffffff', ash: isMobile ? '#888' : '#888888', firefly: '#ffff88', petal: '#ffb7c5'};
  var c = colors[p.type] || '#ffffff';
  var count = isMobile ? 10 : 15;
  for (var i = 0; i < count; i++) {
    var pt = document.createElement('div'); pt.className = 'particle';
    pt.style.left = Math.random() * 100 + '%';
    pt.style.top = '-10px';
    pt.style.width = (isMobile ? (2 + Math.random() * 4) : (3 + Math.random() * 5)) + 'px';
    pt.style.height = pt.style.width;
    pt.style.background = c;
    pt.style.borderRadius = '50%';
    pt.style.animationDuration = (isMobile ? (3 + Math.random() * 3) : (4 + Math.random() * 4)) + 's';
    if (!isMobile) pt.style.animationDelay = Math.random() * 3 + 's';
    document.body.appendChild(pt);
    _hookSchedule(function() { pt.remove(); }, isMobile ? 7000 : 8000);
  }
  next();
}

// ═══ Unified dispatch table ═══════════════════════════════
var _EFFECT_DISPATCH = {
  flash_red: _eff_flash_red,
  screen_shake: _eff_screen_shake,
  golden_glow: _eff_golden_glow,
  vignette_pulse: _eff_vignette_pulse,
  blood_edge: _eff_blood_edge,
  heartbeat_warm: _eff_heartbeat_warm,
  breathing: _eff_breathing,
  glitch_text: _eff_glitch_text,
  screen_blur: _eff_screen_blur,
  portrait_popup: _eff_portrait_popup,
  ending_card: _eff_ending_card,
  clue_image: _eff_clue_image,
  note_card: _eff_note_card,
  typewriter: _eff_typewriter,
  fullscreen_text: _eff_fullscreen_text,
  chapter_title: _eff_chapter_title,
  scene_transition: _eff_scene_transition,
  diary_flip: _eff_diary_flip,
  npc_chat: _eff_npc_chat,
  npc_enter: _eff_npc_enter,
  npc_exit: _eff_npc_exit,
  fav_animation: _eff_fav_animation,
  expression_change: _eff_expression_change,
  binary_choice: _eff_binary_choice,
  input_lock: _eff_input_lock,
  reveal_tag: _eff_reveal_tag,
  rule_reveal: _eff_rule_reveal,
  border_color: _eff_border_color,
  chat_bg: _eff_chat_bg,
  status_flash: _eff_status_flash,
  music_box: _eff_music_box,
  sudden_silence: _eff_sudden_silence,
  button_morph: _eff_button_morph,
  bg_music: _eff_bg_music,
  sound_fx: _eff_sound_fx,
  color_tone: _eff_color_tone,
  particle: _eff_particles,
  particles: _eff_particles,
  petal_fall: _eff_petal_fall,
  sunlight: _eff_sunlight,
  warm_flashback: _eff_warm_flashback,
  fullscreen_text_popup: _eff_fullscreen_text_popup,
  dialogue_bubble: _eff_dialogue_bubble,
  npc_comfort: _eff_npc_comfort,
  scene_illustration: _eff_scene_illustration,
  give_item: _eff_give_item,
  attr_change: _eff_attr_change,
  point_reward: _eff_point_reward,
  local_flag: _eff_local_flag
};

window.renderHookEffect = function renderHookEffect(type, params, next) {
  if (!type) { if (next) _hookSchedule(next, 0); return; }
  // Comfort check
  if (!window.shouldPlay(type)) {
    if (['flash_red','screen_shake','glitch_text'].indexOf(type) >= 0) window.degradeNotice(type.replace(/_/g, ' '));
    else if (['portrait_popup','clue_image','ending_card','binary_choice'].indexOf(type) >= 0) {
      setTimeout(function() { window.degradeNotice(type.replace(/_/g, ' ')); }, 3000);
    }
    if (next) _hookSchedule(next, 0);
    return;
  }
  var fn = _EFFECT_DISPATCH[type];
  if (fn) {
    fn(params || {}, next || function() {});
  } else {
    console.log('Unknown hook effect:', type);
    if (next) _hookSchedule(next, 0);
  }
};
