const socket = io();
const c = document.getElementById('game'), x = c.getContext('2d');
const hud = document.getElementById('hud'), tips = document.getElementById('tips');
const chatInput = document.getElementById('chatInput');
const auth = document.getElementById('auth'), authMsg = document.getElementById('authMsg');
const TILE=32; let world={w:192,h:192,weather:'clear',season:'spring',day_time:420}, me=null;
let players=new Map(), bubbles=new Map(), hint='';

function tileKind(tx,ty){ const n=((Math.abs(((tx*73856093)^(ty*19349663))%1000))/1000 + (Math.abs((((tx+13)*73856093)^((ty-7)*19349663))%1000))/1000 + (Math.abs((((tx-31)*73856093)^((ty+17)*19349663))%1000))/1000)/3; if(tx===0||ty===0||tx===world.w-1||ty===world.h-1) return 'wall'; if(n<0.2) return 'water'; if(n>0.82) return 'mountain'; if(n>0.58) return 'forest'; return 'plain'; }
function color(t){return t==='water'?'#2a77b3':t==='mountain'?'#5f6368':t==='forest'?'#2f7d32':t==='wall'?'#2b2b2b':'#89b35b'}

function drawCharacter(p,sx,sy,self=false){ x.fillStyle=self?'#ffd166':'#ff7b7b'; x.fillRect(sx+10,sy+6,12,12); x.fillStyle='#f3d7b6'; x.fillRect(sx+12,sy+2,8,5); x.fillStyle='#1a1a1a'; if(p.sprite==='miner') x.fillRect(sx+9,sy+1,14,2); if(p.sprite==='ranger') x.fillRect(sx+8,sy+4,3,10); x.fillStyle='#fff'; x.font='10px monospace'; x.fillText(p.n||p.u,sx-4,sy-4); const b=bubbles.get(p.id); if(b&&Date.now()-b.ts<5000){x.fillStyle='#000b';x.fillRect(sx-6,sy-28,x.measureText(b.msg).width+8,16);x.fillStyle='#fff';x.fillText(b.msg,sx-2,sy-16);} }

function draw(){ if(!me){ requestAnimationFrame(draw); return; } x.clearRect(0,0,c.width,c.height); const vx=Math.ceil(c.width/TILE)+2, vy=Math.ceil(c.height/TILE)+2; const sx=me.x-Math.floor(vx/2), sy=me.y-Math.floor(vy/2);
 for(let j=0;j<vy;j++) for(let i=0;i<vx;i++){ const tx=sx+i,ty=sy+j; if(tx<0||ty<0||tx>=world.w||ty>=world.h)continue; const t=tileKind(tx,ty); x.fillStyle=color(t); x.fillRect(i*TILE,j*TILE,TILE,TILE); if(t==='forest'){x.fillStyle='#1f4f20';x.fillRect(i*TILE+11,j*TILE+9,10,15)} if(t==='mountain'){x.fillStyle='#cfd2d6';x.beginPath();x.moveTo(i*TILE+7,j*TILE+25);x.lineTo(i*TILE+16,j*TILE+7);x.lineTo(i*TILE+25,j*TILE+25);x.fill()} if(t==='water'){x.fillStyle='#61b4f355';x.fillRect(i*TILE,j*TILE,TILE,TILE)} }
 players.forEach(p=>{ const px=c.width/2+(p.x-me.x)*TILE, py=c.height/2+(p.y-me.y)*TILE; if(px>-TILE&&py>-TILE&&px<c.width+TILE&&py<c.height+TILE) drawCharacter(p,px,py,p.id===me.id); });
 hud.innerHTML=`<b>${me.n}</b> (${me.x},${me.y})<br>Vida ${me.life.toFixed(1)} Salud ${me.health.toFixed(1)}<br>Hambre ${me.hunger.toFixed(1)} Sed ${me.thirst.toFixed(1)} Energía ${me.energy.toFixed(1)}<br>Temp ${me.temperature.toFixed(1)}° Clima ${world.weather}<br>Inv: madera ${me.wood||0}, piedra ${me.stone||0}, mineral ${me.ore||0}, fibra ${me.fiber||0}`;
 tips.innerHTML=`<b>Atajos</b><br>WASD/Flechas mover<br>E recolectar<br>R descansar<br>F fogata (3 madera + 2 piedra)<br>T herramienta (2 madera + 1 piedra)<br>G beber (junto a agua)<br>H comerciar con cercano<br>${hint?`<hr>${hint}`:''}`;
 requestAnimationFrame(draw);
}

socket.on('auth',d=>{authMsg.textContent=d.ok?'OK ✔':(d.error||'error'); if(d.ok&&d.mode==='login') auth.style.display='none';});
socket.on('bootstrap',d=>{me=d.self; world=d.world; players.clear(); d.players.forEach(p=>players.set(p.id,p)); players.set(me.player_id||me.id,{...me,id:me.player_id||me.id});});
socket.on('delta',d=>{world={...world,...d.world}; (d.players||[]).forEach(p=>{players.set(p.id,{...(players.get(p.id)||{}),...p}); if(me&&(p.id===(me.player_id||me.id))) me={...me,...p};});});
socket.on('chat_bubble',d=>bubbles.set(d.id,{msg:d.msg,ts:Date.now()}));
socket.on('hint',d=>{hint=d.msg; setTimeout(()=>{if(hint===d.msg)hint='';},3000);});

document.getElementById('loginBtn').onclick=()=>socket.emit('login',{username:u.value,password:p.value});
document.getElementById('regBtn').onclick=()=>socket.emit('register',{username:u.value,password:p.value,char_name:n.value,sprite:s.value});

window.addEventListener('keydown',e=>{ if(!me) return; let dx=0,dy=0; if(e.key==='w'||e.key==='ArrowUp')dy=-1; if(e.key==='s'||e.key==='ArrowDown')dy=1; if(e.key==='a'||e.key==='ArrowLeft')dx=-1; if(e.key==='d'||e.key==='ArrowRight')dx=1; if(dx||dy)socket.emit('move',{dx,dy}); if(e.key==='e')socket.emit('action',{kind:'gather'}); if(e.key==='r')socket.emit('action',{kind:'rest'}); if(e.key==='f')socket.emit('action',{kind:'craft_fire'}); if(e.key==='t')socket.emit('action',{kind:'craft_tool'}); if(e.key==='g')socket.emit('action',{kind:'drink'}); if(e.key==='h'){ const near=[...players.values()].find(p=>p.id!==(me.player_id||me.id)&&Math.abs(p.x-me.x)<=1&&Math.abs(p.y-me.y)<=1); if(near) socket.emit('trade_request',{target_id:near.id,item:'wood',qty:1}); else hint='No hay jugador adyacente para trade.'; } });
chatInput.addEventListener('keydown',e=>{ if(e.key==='Enter'){const msg=chatInput.value.trim(); if(msg) socket.emit('chat',{msg}); chatInput.value=''; }});
requestAnimationFrame(draw);
