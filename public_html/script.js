const burger=document.querySelector('.burger'),menu=document.getElementById('menu');
burger.addEventListener('click',()=>{const o=menu.classList.toggle('open');burger.setAttribute('aria-expanded',o)});
menu.addEventListener('click',e=>{if(e.target.tagName==='A'){menu.classList.remove('open');burger.setAttribute('aria-expanded','false')}});
document.getElementById('y').textContent=new Date().getFullYear();
const io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target)}}),{threshold:.12});
document.querySelectorAll('.reveal').forEach(el=>io.observe(el));

// Numéro WhatsApp au format international, sans + ni espaces (ex : 33612345678)
const WHATSAPP_NUMBER='33600000000';
const WHATSAPP_MESSAGE='Bonjour, je vous contacte depuis votre site Au gré des envies.';
document.querySelectorAll('[data-wa]').forEach(a=>{a.href='https://wa.me/'+WHATSAPP_NUMBER+'?text='+encodeURIComponent(WHATSAPP_MESSAGE)});
