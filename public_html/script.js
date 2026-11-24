const burger=document.querySelector('.burger'),menu=document.getElementById('menu');
burger.addEventListener('click',()=>{const o=menu.classList.toggle('open');burger.setAttribute('aria-expanded',o)});
menu.addEventListener('click',e=>{if(e.target.tagName==='A'){menu.classList.remove('open');burger.setAttribute('aria-expanded','false')}});
document.getElementById('y').textContent=new Date().getFullYear();
const io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target)}}),{threshold:.12});
document.querySelectorAll('.reveal').forEach(el=>io.observe(el));

// ---- Contact WhatsApp direct (lien de secours) ----
// Numéro au format international, sans + ni espaces (ex : 33612345678)
const WHATSAPP_NUMBER='33600000000';
const WHATSAPP_URL='https://wa.me/'+WHATSAPP_NUMBER+'?text='+encodeURIComponent('Bonjour, je vous contacte depuis votre site Au gré des envies.');

// ---- Assistant de discussion (n8n) ----
const CHAT_URL='https://n8n-nrog.srv1999096.hstgr.cloud/webhook/d01a1ea6-f143-4bda-9cb3-f4aacb5231c4/chat';
const WELCOME='Bonjour et bienvenue chez Au gré des envies ! 🌸 Parlez-moi de votre projet : fleurs en tissu, lingettes lavables, accessoires ou création sur mesure ?';
const sid=(()=>{try{let v=localStorage.getItem('agde_sid');if(!v){v=(crypto.randomUUID?crypto.randomUUID():String(Date.now())+Math.random());localStorage.setItem('agde_sid',v)}return v}catch(e){return String(Date.now())+Math.random()}})();

const panel=document.createElement('div');
panel.className='chat';panel.setAttribute('role','dialog');panel.setAttribute('aria-label','Discussion avec l\'atelier');
panel.innerHTML='<div class="chat-head"><div><b>Au gré des envies</b><small>Parlons de votre projet</small></div><button class="chat-x" type="button" aria-label="Fermer">&times;</button></div>'+
'<div class="chat-log" aria-live="polite"></div>'+
'<form class="chat-form"><input name="m" placeholder="Votre message…" autocomplete="off" maxlength="600" required><button type="submit">Envoyer</button></form>'+
'<div class="chat-foot">Ou écrivez directement sur <a href="'+WHATSAPP_URL+'" target="_blank" rel="noopener">WhatsApp</a></div>';
document.body.appendChild(panel);
const log=panel.querySelector('.chat-log'),form=panel.querySelector('form'),input=form.m,sendBtn=form.querySelector('button');
function add(t,c){const d=document.createElement('div');d.className='msg '+c;d.textContent=t;log.appendChild(d);log.scrollTop=log.scrollHeight;return d}
let greeted=false;
function openChat(e){if(e)e.preventDefault();panel.classList.add('open');if(!greeted){greeted=true;add(WELCOME,'bot')}input.focus()}
document.querySelectorAll('[data-chat]').forEach(a=>a.addEventListener('click',e=>{openChat(e);menu.classList.remove('open');burger.setAttribute('aria-expanded','false')}));
panel.querySelector('.chat-x').addEventListener('click',()=>panel.classList.remove('open'));
document.addEventListener('keydown',e=>{if(e.key==='Escape')panel.classList.remove('open')});
form.addEventListener('submit',async e=>{
  e.preventDefault();const t=input.value.trim();if(!t)return;
  add(t,'me');input.value='';sendBtn.disabled=true;
  const w=add('…','bot typing');
  try{
    const r=await fetch(CHAT_URL,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'sendMessage',sessionId:sid,chatInput:t})});
    if(!r.ok)throw new Error(r.status);
    const d=await r.json();
    w.className='msg bot';w.textContent=d.output||d.text||'Merci ! La créatrice vous répondra très vite.';
  }catch(err){
    w.className='msg bot';w.innerHTML='Je suis momentanément indisponible. Vous pouvez écrire directement à la créatrice sur <a href="'+WHATSAPP_URL+'" target="_blank" rel="noopener">WhatsApp</a>.';
  }
  sendBtn.disabled=false;log.scrollTop=log.scrollHeight;input.focus();
});
