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
'<div class="chat-note">Assistant automatisé (IA) : vos messages sont traités pour répondre à votre demande. <a href="confidentialite.html" target="_blank">Confidentialité</a></div>'+
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

// ---- Boutique : onglets + quantités + demande de devis ----
// Pour ajouter une photo : mettre le chemin dans "img" (ex : 'images/bouquet-rose.jpg') après l'avoir déposée dans le dossier images/.
// "prix" est facultatif (ex : 'À partir de 25 €'). Les noms ci-dessous sont des exemples à remplacer.
const CATALOGUE={
 'Décoration florale':[
  {id:'f1',nom:'Bouquet de fleurs en tissu',desc:'Composition sur mesure aux couleurs de votre choix.',prix:'Sur devis',img:''},
  {id:'f2',nom:'Couronne florale',desc:'Pour la porte, la table ou une occasion spéciale.',prix:'Sur devis',img:''},
  {id:'f3',nom:'Fleur unique à la tige',desc:'La touche florale qui ne fane jamais.',prix:'Sur devis',img:''}],
 'Lingettes lavables':[
  {id:'l1',nom:'Lot de lingettes démaquillantes',desc:'Coton doux, réutilisables, lavables en machine.',prix:'Sur devis',img:''},
  {id:'l2',nom:'Lingettes bébé',desc:'Extra-douces pour la peau délicate.',prix:'Sur devis',img:''},
  {id:'l3',nom:'Essuie-tout lavable',desc:'Une alternative zéro déchet pour la cuisine.',prix:'Sur devis',img:''}],
 'Accessoires':[
  {id:'a1',nom:'Pochette zippée',desc:'Pratique et unique, à choisir dans mes tissus.',prix:'Sur devis',img:''},
  {id:'a2',nom:'Chouchou',desc:'Tissus fleuris et unis, en lot ou à l\'unité.',prix:'Sur devis',img:''},
  {id:'a3',nom:'Tote bag',desc:'Sac cousu main, résistant et élégant.',prix:'Sur devis',img:''}]
};
const tabsEl=document.getElementById('tabs'),shopEl=document.getElementById('shop'),cartEl=document.getElementById('cart');
const qte={};let tabActif=Object.keys(CATALOGUE)[0];
const nomDe=id=>{for(const k in CATALOGUE){const p=CATALOGUE[k].find(x=>x.id===id);if(p)return p.nom}return id};
function dessinerOnglets(){
  tabsEl.innerHTML='';
  Object.keys(CATALOGUE).forEach(k=>{
    const b=document.createElement('button');b.type='button';b.className='tab';b.setAttribute('role','tab');
    b.setAttribute('aria-selected',k===tabActif);b.textContent=k;
    b.addEventListener('click',()=>{tabActif=k;dessinerOnglets();dessinerProduits()});
    tabsEl.appendChild(b);
  });
}
function dessinerProduits(){
  shopEl.innerHTML='';
  CATALOGUE[tabActif].forEach((p,i)=>{
    const card=document.createElement('article');card.className='prod';
    const ph=document.createElement('div');ph.className='ph t'+((i%3)+1);
    if(p.img){const im=document.createElement('img');im.src=p.img;im.alt=p.nom;im.loading='lazy';ph.appendChild(im)}
    else ph.innerHTML='<svg><use href="#'+(tabActif==='Décoration florale'?'flower':'branch')+'"/></svg>';
    const body=document.createElement('div');body.className='prod-body';
    body.innerHTML='<h3></h3><p></p><span class="price"></span><div class="qty"><small>Quantité</small><div class="qty-ctl"><button type="button" aria-label="Moins">&minus;</button><span>0</span><button type="button" aria-label="Plus">+</button></div></div>';
    body.querySelector('h3').textContent=p.nom;body.querySelector('p').textContent=p.desc;body.querySelector('.price').textContent=p.prix||'';
    const val=body.querySelector('.qty-ctl span'),[moins,plus]=body.querySelectorAll('.qty-ctl button');
    val.textContent=qte[p.id]||0;
    moins.addEventListener('click',()=>{qte[p.id]=Math.max(0,(qte[p.id]||0)-1);val.textContent=qte[p.id];majPanier()});
    plus.addEventListener('click',()=>{qte[p.id]=Math.min(999,(qte[p.id]||0)+1);val.textContent=qte[p.id];majPanier()});
    card.append(ph,body);shopEl.appendChild(card);
  });
}
function texteDemande(){
  const l=Object.keys(qte).filter(id=>qte[id]>0).map(id=>'- '+qte[id]+' x '+nomDe(id));
  return 'Bonjour, je souhaite un devis pour :\n'+l.join('\n');
}
function majPanier(){
  const ids=Object.keys(qte).filter(id=>qte[id]>0);
  cartEl.hidden=!ids.length;
  if(!ids.length)return;
  const total=ids.reduce((n,id)=>n+qte[id],0);
  document.getElementById('cart-count').textContent=total+' article'+(total>1?'s':'')+' sélectionné'+(total>1?'s':'');
  document.getElementById('cart-list').textContent=ids.map(id=>qte[id]+' × '+nomDe(id)).join(' · ');
  document.getElementById('cart-wa').href='https://wa.me/'+WHATSAPP_NUMBER+'?text='+encodeURIComponent(texteDemande());
}
document.getElementById('cart-quote').addEventListener('click',()=>{
  const m=document.querySelector('#form textarea[name=message]');
  if(m)m.value=texteDemande()+'\n\n';
  document.getElementById('contact').scrollIntoView({behavior:'smooth'});
  if(m)setTimeout(()=>m.focus({preventScroll:true}),600);
});
dessinerOnglets();dessinerProduits();
