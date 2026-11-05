'use strict';
// ---- the real font: /font reads the build's vwf_font.bin + vwf_width.bin,
// plus the retail Japanese FONT.BIN and its glyph map, which draws every
// character the English font has no cell for. The baked copy below is only
// what a file:// open (no server) falls back to.
const WIDTH_FALLBACK="BAQHCQEHCAQFBQgHBAcECAgGCAgIBwgICAgEBAcICAkBCAgICAgICAgECAgICAkICAgJCAgJCAgICAgBCAEBAQYICAcIBwYICAQFCAQIBwcICAcHBggICAgIBwYFBggJAQg=";
const FONT_FALLBACK="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";
let ADV=Uint8Array.from(atob(WIDTH_FALLBACK),c=>c.charCodeAt(0));
let FONT=Uint8Array.from(atob(FONT_FALLBACK),c=>c.charCodeAt(0));
let ORIG=null, GMAP={};
function loadFont(){
  return fetch('/font').then(r=>r.ok?r.json():Promise.reject())
    .then(d=>{ADV=Uint8Array.from(atob(d.widths),c=>c.charCodeAt(0));
              FONT=Uint8Array.from(atob(d.font),c=>c.charCodeAt(0));
              if(d.orig){
                ORIG=Uint8Array.from(atob(d.orig),c=>c.charCodeAt(0));
                GMAP=d.map||{};
              }
              render();})
    .catch(()=>{});
}
const BOX=239, SCROLL_ROWS=3;
const EXTRA={'…':0x7F,'＊':0x80,'￥':0x81};
const SPELL={'＊':'*','’':"'",'‘':"'",'“':'"','”':'"','–':'-','—':'-','−':'-','＞':'>'};
const ARTICLES=new Set(['a','an','the','this','these','those','its','their','his','her','our','your','my']);
const CONNECTORS=new Set(['to','of','in','on','at','with','from','for','by','as','and','or','but','nor','than','that','into','onto','about','over','under','off','upon','without','through','toward','towards','between','among','against','because','while','when','where','if','so','yet']);
const CLOSERS=/^[.,!?;:'…»)\]]/;
const ABBREV=new Set(['mr','mrs','ms','dr','st','jr','sr','vs','etc','no','fig','sen']);
const CODE=/<[^>]+>/g;

function fold(ch){return SPELL[ch]||ch}
function code(ch){const c=fold(ch);const o=c.codePointAt(0);
  if(o>=0x20&&o<=0x7E)return o;
  if(EXTRA[c]!==undefined)return EXTRA[c];
  return null}
function cw(ch){const k=code(ch);return k===null?16:ADV[k-0x20]}
// control codes and their parameter bytes (a name insert's あ, <FFFD>'s
// branch character - "ヌ" in the demon lines) never print and never measure.
const CODE_PARAM=/<FFFD>.|<FF(07|08|0F)>あ|<[^>]+>/g;
// THE TEXT AS THE FILE HAS IT, with the codes made readable instead of
// deleted: `\n` is a line break, `␌` a new box, `⏸` a wait, `{name}` the
// player's name slot. The list preview uses it; the editor and the sources
// show the literal codes.
function pretty(s){
  return s
    .replace(/<FFFD>(.)/g, '⏸$1')
    .replace(/<FF(07|08|0F)>(あ|<[^>]*>)?/g, (m, k) => k === '08' ? '{nick}' : '{name}')
    .replace(/<FFF6>/g, '\\n')
    .replace(/<FF03>/g, '\\n')
    .replace(/<FF04>/g, '␌')
    .replace(/<FF02>/g, '⏸')
    .replace(/<FF0E><[0-9A-F]{2}>/g, '❓')
    .replace(/<FF05><[0-9A-F]{2}><[0-9A-F]{2}>/g, '⋯')
    .replace(/<FF01>/g, '⏹')
    .replace(CODE_PARAM, '')
    .replace(/<[^>]+>/g, '');
}
// the player's name, for measuring and drawing: the entry's 5 widest glyphs
const NAME_PH = /<FF(07|0F)>((?:あ|<[^>]*>)?)|<FF08>((?:あ|<[^>]*>)?)/g;
function withPlaceholder(s){return s.replace(NAME_PH, '{name}')}
function textWidth(s){
  // <FF0F>あ and friends: a name the entry can type (5 wide glyphs)
  s=s.replace(/<FF(07|0F|08)>(あ|<[^>]*>)/g,(m,a)=>{const n={ '07':5,'0F':5,'08':8 }[a];return 'R'.repeat(n)});
  s=s.replace(/<FFFD>./g,'');
  s=s.replace(/<FF(07|0F|08)>(あ|<[^>]*>)?/g,'RRRRR');
  let w=0;
  for(const part of s.split(/(<[^>]+>)/)) if(!/^<[^>]+>$/.test(part)) for(const ch of part) w+=cw(ch);
  return w;
}
function sentEnd(w){
  const t=w.replace(CODE,'').replace(/\s+$/,'');
  if(!/[.!?…]["'”)\]]?$/.test(t))return false;
  const core=t.replace(/[.!?…]+["'”)\]]?$/,'').toLowerCase();
  if(/^[a-z]$/.test(core))return false;
  return !ABBREV.has(core);
}
function capsWord(w){
  let t=w.replace(/^["'“‘(\[{]+/,'').replace(/["'”’)\]}]+$/,'');
  if(t.replace(/[,;:]$/,'').length<2||!/^[A-Z]/.test(t))return false;
  if(t.endsWith(':'))return false;
  return !sentEnd(w);
}
function coreWord(w){return w.replace(/^["'“‘(\[{]+/,'')}

// ---- glue + name marks (mirrors vwf_wrap._glue_items) ----
function items(text){
  let out=text.split(/\s+/).filter(x=>x).map(w=>['w',w]);
  for(let i=out.length-2;i>=0;i--){
    const a=out[i],b=out[i+1];
    if(a[0]==='w'&&b[0]==='w'){
      const t=coreWord(a[1]);
      if(ARTICLES.has(t.replace(/[,;:]$/,'').toLowerCase())&&!/[.!?…]$/.test(t)&&!CLOSERS.test(b[1]))
        out.splice(i,2,['w',a[1]+' '+b[1]]);
    }
  }
  const g=[];
  for(const it of out){
    if(it[0]==='w'&&g.length&&g[g.length-1][0]==='w'&&
       CONNECTORS.has(coreWord(it[1]).replace(/[,;:]$/,'').toLowerCase())&&
       !sentEnd(g[g.length-1][1])&&!CLOSERS.test(it[1]))
      g[g.length-1]=['w',g[g.length-1][1]+' '+it[1]];
    else g.push(it.slice());
  }
  let prev=null,run=0;
  for(const it of g){
    if(it[0]!=='w'){prev=null;run=0;continue}
    if(prev!==null&&run<9&&capsWord(prev)&&capsWord(it[1])&&!sentEnd(prev)){run++;it[2]=run}
    else run=0;
    prev=it[1];
  }
  return g;
}
function pieces(w){
  const cuts=[];
  for(const m of w.matchAll(/<[^>]+>/g)){if(m.index>0)cuts.push(m.index);if(m.index+m[0].length<w.length)cuts.push(m.index+m[0].length)}
  let start=1;
  while(true){const k=w.indexOf('-',start);if(k<1||k>=w.length-1)break;
    if(!/[A-Za-z0-9']/.test(w.slice(k+1)))break;cuts.push(k+1);start=k+1}
  const uniq=[...new Set(cuts)].filter(c=>c>0&&c<w.length).sort((a,b)=>a-b);
  const out=[];let prev=0;
  for(const c of uniq.concat([w.length])){out.push([w.slice(prev,c),prev>0]);prev=c}
  return out.length?out:[[w,false]];
}
function atoms(text){
  const seq=[];let prev=null,hold=false;
  for(const it of items(text)){
    const word=it[1], mark=it[2]||0;
    const closer=word&&CLOSERS.test(word)&&prev!==null&&
      !(("'’").includes(word[0])&&word.length>1&&/[A-Za-z0-9]/.test(word[1]));
    let join,brk;
    if(closer){join='';brk=word.startsWith('..')}
    else{join=prev!==null?' ':'';brk=true}
    if(hold)brk=false;
    const ps=pieces(word);
    const t0=coreWord(word);
    hold=ARTICLES.has(t0.replace(/[,;:]$/,'').toLowerCase())&&!/[.!?…]$/.test(t0);
    ps.forEach(([t,inner],k)=>{
      seq.push({t,join:k===0?join:'',brk:k===0?brk:inner,pen:k?1:0,
                nbrk:k===0&&!!mark,fin:false});
    });
    prev=seq[seq.length-1];
  }
  // the pen-240 allowance: only a line holding the very last word may use it
  let more=false;
  for(let k=seq.length-1;k>=0;k--){seq[k].fin=(!more && k===seq.length-1);more=more||true}
  return seq;
}
function lineText(cur,a){return cur+((cur&&a.join)?a.join:'')+a.t}
// ---- the layout search (mirrors vwf_wrap.flow_layout) ----
function layout(ats,width=BOX){
  const n=ats.length;if(!n)return[];
  const best=[...Array(n)].map(()=>({}));
  best.push({0:{c:[0,0,0,0,0,-1],end:-1}});
  for(let i=n-1;i>=0;i--){
    let text=ats[i].t,w=textWidth(text),j=i;
    for(;;){
      const lim=ats[j].fin?width+1:width;
      const over=w-lim, base=over>0?over:0;
      if(j+1===n||ats[j+1].brk){
        for(const kk of Object.keys(best[j+1])){
          const sub=best[j+1][kk].c, k=+kk;
          const step=sub[5]-w;
          const trans=sub[5]>=0?(step*step+(step>0?step*step:0)):0;
          const tot=[base+sub[0],
                     (i?ats[i].pen:0)+sub[1],
                     (ats[i].nbrk?1:0)+sub[2],
                     sub[3]+((j+1===n||sentEnd(text))?0:1),
                     sub[4]-(w*w)*(k+2)+trans,
                     w];
          const cur=best[i][k+1];
          if(!cur||cmp(tot,cur.c)<0)best[i][k+1]={c:tot,end:j};
        }
        if(over>0)break;
      }
      if(j+1>=n)break;
      j++;text=lineText(text,ats[j]);w=textWidth(text);
    }
  }
  let pick=null;
  for(const kk of Object.keys(best[0])){
    const c=best[0][kk].c,k=+kk;
    const key=[c[0],k,c[1],c[2],c[3],c[4]];
    if(!pick||cmp(key,pick.key)<0)pick={k,key};
  }
  const out=[];let i=0,k=pick.k;
  while(i<n){const j=best[i][k].end;out.push([i,j]);i=j+1;k--}
  return out;
}
function cmp(a,b){for(let i=0;i<a.length;i++){if(a[i]!==b[i])return a[i]-b[i]}return 0}
function flowLines(text){
  // A NEWLINE IN THE BOX IS A BREAK YOU ASKED FOR: the flow wraps each run
  // between them and never moves one.
  const out = [];
  for(const part of text.split('\n')){
    if(!part.trim()) continue;
    const ats = atoms(part);
    for(const [i2,j2] of layout(ats)){
      let s = '';
      for(let k=i2;k<=j2;k++) s = lineText(s, ats[k]);
      out.push(s);
    }
  }
  return out;
}

// ---- pagination: 3 lines, one scroll, then a NEW box ----
function paginate2(text){
  const pages = [];
  for(const boxText of text.split(/\n{2,}/)){
    if(!boxText.trim()) continue;
    const parts = boxText.split(/\n⏸\n/);
    const lines = [];
    parts.forEach((part, pi) => {
      if(pi) lines.push('\u0000SCROLL\u0000');
      for(const l of flowLines(part)) lines.push(l);
    });
    let cur = null;
    const open = () => { cur = {visible: [], scrolled: []}; pages.push(cur); return cur; };
    open();
    for(const l of lines){
      if(l === '\u0000SCROLL\u0000'){
        if(cur.scrolled.length) open();
        continue;
      }
      const target = !cur.scrolled.length && cur.visible.length < 3
        ? cur.visible : cur.scrolled;
      target.push(l);
      if(target === cur.scrolled && cur.scrolled.length === 3) open();
    }
  }
  return {lines: pages.flatMap(p => p.visible.concat(p.scrolled)), pages};
}

// what the box really shows for one stored line: the player's name stands in
// as {name} (5 glyphs, the entry's cap), every other code is invisible
function drawText(s){
  return withPlaceholder(s).replace(/<FFFD>./g, '').replace(/<[^>]+>/g, '');
}

// ---- the stored layout: what the FILE says, box by box ----
// A row is read as authored: <FF04> starts a new box, <FF03> a line, <FF02>
// the box's one scroll. So the viewer shows the row the way the disc will,
// not a re-wrap that might disagree with it. A literal newline in a draft is
// a line break too (the save refuses it: one row is one TSV line).
function cleanLine(t){
  // the box's TAIL is codes, not text: <FF01> ends it, <FF06>xx<FF00> is the
  // portrait frame. Leaving them in the line made it measure too wide.
  return t.replace(/<FF01>|<FFEF>|<FFF5>/g, '')
          .replace(/<FF06><[0-9A-Fa-f]{2}>|<FF00>/g, '')
          .trim();
}
function storedBoxes(en){
  const out = [];
  for(const raw of en.split('<FF04>')){
    const visible = [], scrolled = [];
    let after = false;
    // THE LINE BREAK IS THE FAMILY'S (<FF03> dialogue, <FFF6> battle), and a
    // <FF02> with nothing after it is the box's DISMISSAL press, not a scroll.
    for(const seg of raw.split(/(<FF03>|<FFF6>|<FFFB><FFF7>|<FF02>)/)){
      if(seg === '<FF03>' || seg === '<FFF6>') continue;
      if(seg === '<FF02>' || seg === '<FFFB><FFF7>'){ after = true; continue; }
      for(const piece of seg.split(/\r?\n/)){
        const t = cleanLine(piece);
        if(!t.replace(/<[^>]+>/g, '').trim()) continue;   // codes only
        (after ? scrolled : visible).push(t);
      }
    }
    if(visible.length || scrolled.length) out.push({visible, scrolled});
  }
  return out.length ? out : [{visible: [], scrolled: []}];
}

// ---- drawing the real font ----
const cv=document.getElementById('cv'),ctx=cv.getContext('2d');
function drawOrig(ch,x,y,z,color){
  // THE RETAIL JAPANESE FONT: 16x16 1-bpp, 32 bytes per glyph, MSB is the
  // leftmost pixel. Only characters the English font has no cell for reach
  // this; a character with no glyph in either font still gets the box.
  const g=GMAP[ch];
  if(g===undefined||!ORIG){
    ctx.fillStyle=color;ctx.globalAlpha=.25;ctx.fillRect(x,y,16*z,12*z);ctx.globalAlpha=1;
    return 16*z;
  }
  ctx.fillStyle=color;
  for(let r=0;r<16;r++){
    const bits=(ORIG[g*32+r*2]<<8)|ORIG[g*32+r*2+1];
    if(!bits)continue;
    for(let b=0;b<16;b++)if(bits&(0x8000>>b))ctx.fillRect(x+b*z,y+r*z,z,z);
  }
  return 16*z;              // the retail cell is full width
}
function drawGlyph(ch,x,y,z,color){
  const k=code(ch);
  if(k===null)return drawOrig(ch,x,y,z,color);
  const adv=ADV[k-0x20];
  ctx.fillStyle=color;
  for(let r=0;r<16;r++){const bits=FONT[(k-0x20)*16+r];
    if(!bits)continue;
    for(let b=0;b<8;b++)if(bits&(0x80>>b))ctx.fillRect(x+b*z,y+r*z,z,z)}
  return adv*z;              // THE PEN SCALES WITH THE PIXELS
}
function drawLine(line,x,y,z,color,shadow){
  let px=x;
  for(const ch of line){
    if(shadow)drawGlyph(ch,px+Math.max(1,z),y+Math.max(1,z),z,'rgba(0,0,0,.85)');
    px+=drawGlyph(ch,px,y,z,color);
  }
  return px-x;
}
function render(){
  const text=document.getElementById('src').value;
  const z=Math.max(1, Math.round(+document.getElementById('zoom').value));
  const shadow=document.getElementById('shadow').checked;
  const guides=document.getElementById('guides').checked;
  // a picked ROW is drawn as stored from the draft (every box, its own lines);
  // typed text with no row is laid out by the flow so you can watch the rules
  // decide. Editing a row never drops the row: the page follows the draft.
  const boxes = CUR ? storedBoxes(text) : paginate2(text).pages;
  const lines = CUR ? boxes.reduce((a,b)=>a.concat(b.visible, b.scrolled), []) : paginate2(text).lines;
  const PADX=4, PADY=6, GAP=10, ROWS=6;
  const W=(BOX+16)*z, H=boxes.length*((ROWS*16+PADY*2+GAP)*z);
  cv.width=W; cv.height=H; cv.style.width=W+'px'; cv.style.height=H+'px';
  const wrap=document.getElementById('cvwrap');
  if(wrap && wrap.style) wrap.style.minHeight=(H+2)+'px';
  ctx.clearRect(0,0,W,H);
  ctx.fillStyle='#0b1a10'; ctx.fillRect(0,0,W,H);
  const rows=[];
  boxes.forEach((page,bi)=>{
    const base = bi*((ROWS*16+PADY*2+GAP)*z);
    if(guides){
      ctx.fillStyle='rgba(255,255,255,.06)';
      for(let r=0;r<ROWS;r++) ctx.fillRect(0, base+(PADY+r*16)*z, W, 1);
      ctx.fillStyle='rgba(255,255,255,.12)'; ctx.fillRect((PADX+BOX)*z, base, 1, (ROWS*16+PADY*2)*z);
    }
    let y = base + PADY*z;
    page.visible.forEach((l,i)=>{
      drawLine(drawText(l), PADX*z, y, z, '#dfe7df', shadow);
      rows.push([`${bi+1}.${i+1}`, textWidth(l), l]); y += 16*z;
    });
    page.scrolled.forEach((l)=>{
      drawLine(drawText(l), PADX*z, y, z, 'rgba(223,231,223,.42)', false);
      rows.push([`${bi+1}↕`, textWidth(l), l]); y += 16*z;
    });
    if(guides && bi+1 < boxes.length){          // the box boundary
      ctx.fillStyle='rgba(255,255,255,.18)';
      ctx.fillRect(0, base+(ROWS*16+PADY*2+GAP/2)*z, W, 1);
    }
    ctx.fillStyle='rgba(232,193,90,.75)';
    const ax=(PADX+BOX-6)*z, ay=base+(PADY+4*16+3)*z;
    ctx.beginPath(); ctx.moveTo(ax,ay); ctx.lineTo(ax+8*z,ay); ctx.lineTo(ax+4*z,ay+6*z);
    ctx.closePath(); ctx.fill();
  });
  const tb=document.getElementById('lines'); tb.innerHTML='';
  for(const [tag,w,l] of rows){
    const over=w>240, sl=tag.includes('↕');
    tb.insertAdjacentHTML('beforeend',
      `<tr><td class="${sl?'pg':'w'}">${tag}</td>`+
      `<td class="w ${over?'warn':''}">${Math.round(w)}</td>`+
      `<td class="${sl?'pg':''}">${esc(l)}</td></tr>`);
  }
  const viol=violations(lines);
  document.getElementById('stat').innerHTML=
    `<span class="${viol.length?'warn':'ok'}">${viol.length?viol.join(' · '):'no rule broken'}</span>`+
    ` · ${lines.length} lines · ${boxes.length} box(es)`;
}
function violations(lines){
  const v=[];
  lines.forEach((l,i)=>{
    const w=textWidth(l);if(w>240)v.push(`line ${i+1} is ${w}px`);
    if(i>0){const first=l.split(/\s+/)[0].replace(/^["'“‘(\[{]+/,'').replace(/[,;:]$/,'').toLowerCase();
      // AN ARTICLE AT A LINE START IS CORRECT: articles glue FORWARD to their
      // noun ("the hospital" is one atom). Only a CONNECTOR must end the line
      // it sits on (it glues backwards).
      if(CONNECTORS.has(first))v.push(`line ${i+1} starts with "${first}"`)}
  });
  return v;
}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;')}

// ---- state ----
let ROWS = [], FAM = 'ALL', MANF = 'all', SHOWN = [], PAINTED = 0;
let CUR = null;                     // the row detail the box is showing
let DIRTY = false;                  // the draft differs from what is stored
let MODE = 'rows';                  // rows | psp
let HITS = [], HITSEQ = 0, REF = null;
const ROW_EL = new Map();
const CHUNK = 400;
const $ = id => document.getElementById(id);

function families(){
  const seen = {};
  for(const [rel] of ROWS) seen[rel.split('/')[0]] = (seen[rel.split('/')[0]] || 0) + 1;
  return seen;
}
function fillFamilies(){
  const sel = $('fam'), fams = families();
  sel.innerHTML = `<option value="ALL">all families (${ROWS.length})</option>` +
    Object.keys(fams).sort().map(f => `<option value="${f}">${f} (${fams[f]})</option>`).join('');
  sel.value = FAM;
}
const wordsIn = (en) => pretty(en).split(/\s+/).filter(w => w && !/^[⏸␌⏹❓⋯]+$/.test(w)).length;
function matches(q){
  const longonly = $('longonly').checked;
  const needle = q.toLowerCase();
  return ROWS.filter(r => {
    const [rel, id, pos, text, state, note, man] = r;
    if(FAM !== 'ALL' && !rel.startsWith(FAM)) return false;
    // the manual-entry filter: a queued row is a manual row with no en yet,
    // so "has a manual row" covers both; "no manual row" is the untouched
    // generated work. An explicit manual filter is about the human's rows,
    // so the textbox-size heuristic does not hide its short cells.
    if(MANF !== 'all'){
      if(MANF === 'manual' && state !== 'manual') return false;
      if(MANF === 'inman' && !man) return false;
      if(MANF === 'queue' && state !== 'queue') return false;
      if(MANF === 'noman' && man) return false;
    } else if(longonly && (state === 'manual' || state === 'generated') && wordsIn(text) < 3){
      // the 3+ word filter is about English textboxes; a row with no English
      // yet (its draft is the Japanese) is never hidden by it.
      return false;
    }
    if(!needle) return true;
    return (text + ' ' + note + ' ' + rel + ' ' + id + ' ' + pos).toLowerCase().includes(needle);
  });
}

// ---- the list ----
const keyOf = rec => rec[0] + '\u0000' + rec[2];
function stateTag(state){
  const label = {manual:'manual', generated:'generated', queue:'ja · queued', empty:'empty'}[state] || state;
  const cls = {manual:'man', queue:'q', empty:'e'}[state] || '';
  return `<span class="tag ${cls}">${label}</span>`;
}
function rowHtml(rec){
  const [rel, id, pos, text, state, note] = rec;
  return `<div class="k"><span class="fam">${esc(rel)}</span> #${esc(id)}${stateTag(state)}` +
         `${note ? '<span class="tag n">note</span>' : ''}<span class="pg"> · ${esc(pos)}</span>` +
         `<button class="mini" data-act="find" title="open this row and search the PSP text for it">psp</button></div>` +
         `<div class="t">${esc(pretty(text)) || esc(note)}</div>`;
}
function hitHtml(h){
  const [reg, rel, id, pos, text] = h;
  return `<div class="k"><span class="tag ${reg}">${reg.toUpperCase()}</span> ` +
         `<span class="fam">${esc(rel)}</span> #${esc(id)}<span class="pg"> · ${esc(pos)}</span></div>` +
         `<div class="t">${esc(pretty(text))}</div>`;
}
function renderList(){
  const list = $('list');
  list.scrollTop = 0;
  list.innerHTML = '';
  ROW_EL.clear();
  PAINTED = 0;
  // THE LIST GROWS: one chunk is painted, then the scroll handler paints
  // the next as you reach the end. A short list is filled until it can
  // scroll, so the viewport is never half empty with more behind it.
  appendRows();
  fillViewport();
  updateCount();
}
function fillViewport(){
  const list = $('list');
  for(let guard = 0; guard < 50 && PAINTED < SHOWN.length; guard++){
    if(list.scrollHeight > list.clientHeight + 40) break;
    appendRows();
  }
}
function updateCount(){
  const c = $('count');
  if(MODE === 'rows'){
    c.textContent = `${SHOWN.length} row${SHOWN.length === 1 ? '' : 's'}` +
                    (FAM === 'ALL' ? '' : ` in ${FAM}`) +
                    (PAINTED < SHOWN.length ? ` · ${PAINTED} shown` : '');
  } else {
    const q = $('filt').value.trim();
    c.textContent = q
      ? `${SHOWN.length} hit${SHOWN.length === 1 ? '' : 's'}${SHOWN.length >= 300 ? ' (first 300)' : ''}`
      : 'type to search the PSP US + JP extracts';
  }
}
function appendRows(){
  const list = $('list');
  if(PAINTED >= SHOWN.length) return;
  const end = Math.min(SHOWN.length, PAINTED + CHUNK);
  const frag = document.createDocumentFragment();
  for(let i = PAINTED; i < end; i++){
    const d = document.createElement('div');
    d.className = 'row';
    if(MODE === 'rows'){
      const rec = SHOWN[i];
      d.innerHTML = rowHtml(rec);
      d.onclick = e => {
        const hit = e.target && e.target.closest && e.target.closest('[data-act="find"]');
        if(hit) pick(rec).then(ok => { if(ok) findMatches(); });
        else pick(rec);
      };
      ROW_EL.set(keyOf(rec), d);
    } else {
      const h = SHOWN[i];
      d.innerHTML = hitHtml(h);
      d.onclick = () => showRefFor(h);
    }
    frag.appendChild(d);
  }
  list.appendChild(frag);
  PAINTED = end;
  updateCount();
}
function scrollRowIntoView(i){
  const list = $('list');
  while(PAINTED <= i && PAINTED < SHOWN.length) appendRows();
  const row = list.children[i];
  if(row && row.scrollIntoView) row.scrollIntoView({block: 'nearest'});
}

// ---- one row: read it, edit the draft, save the override ----
function setStatus(text, bad){
  const el = $('savestat');
  el.textContent = text || '';
  el.className = 'sub' + (bad ? ' warn' : '');
}
function updateDirty(){
  $('src').classList.toggle('dirty', DIRTY);
  $('save').disabled = !CUR;
  $('find').disabled = !CUR;
  if(DIRTY) setStatus('unsaved');
}
function confirmDiscard(){
  return !DIRTY || confirm('Discard unsaved edits to this row?');
}
function fillSources(d){
  const man = d.man, gen = d.gen;
  $('src_man_meta').textContent = man ? `#${man.id}${man.psp ? ' · ' + man.psp : ''}` : '';
  $('src_man').textContent = man ? (man.en || '(manual row — en still empty)') : '(no manual row at this pos)';
  $('src_note').textContent = man && man.note ? man.note : '(no note)';
  $('src_gen_meta').textContent = gen ? `#${gen.id}${gen.psp ? ' · ' + gen.psp : ''}` : '';
  $('src_gen').textContent = gen ? (gen.en || '(generated row — en still empty)') : '(no generated row at this pos)';
  const seen = new Set(), lines = [];
  for(const r of [man, gen]) if(r && r.psp && !seen.has(r.psp)){
    seen.add(r.psp);
    lines.push((r.psp_text || '(nothing at that PSP locator)') + `\n[${r.psp}]`);
  }
  $('src_psp_meta').textContent = lines.length ? '' : '(no psp pointer)';
  $('src_psp').textContent = lines.length ? lines.join('\n\n') : '(no PSP source for this row)';
  $('src_ja').textContent = d.ja || '(no PSX Japanese at this pos)';
}
function setDetail(d){
  CUR = d;
  const id = (d.gen && d.gen.id) || (d.man && d.man.id) || '';
  $('locid').textContent = `${d.rel}  #${id}  ·  pos ${d.pos}`;
  $('badge').innerHTML = stateTag(d.state);
  fillSources(d);
  updateDirty();
}
async function pick(rec){
  if(!Array.isArray(rec) || !confirmDiscard()) return false;
  try{
    const r = await fetch(`/row?rel=${encodeURIComponent(rec[0])}&pos=${encodeURIComponent(rec[2])}`);
    if(!r.ok) throw new Error('row not found');
    const d = await r.json();
    setDetail(d);
    $('src').value = d.initial;
    DIRTY = false;
    updateDirty();
    setStatus('');
    clearMatches();
    render();
    $('pane').scrollTop = 0;
    return true;
  }catch(e){ setStatus(String(e.message || e), true); return false; }
}
async function saveDraft(){
  if(!CUR){ setStatus('pick a row first — a draft is saved into its manual row', true); return; }
  const en = $('src').value;
  try{
    const r = await fetch('/save', {method:'POST', headers:{'Content-Type':'application/json'},
                                    body: JSON.stringify({rel: CUR.rel, pos: CUR.pos, en})});
    const d = await r.json().catch(() => ({error:'bad response'}));
    if(!r.ok){ setStatus(d.error || 'save failed', true); return; }
    DIRTY = false;
    setDetail(d);
    if($('src').value !== d.initial) $('src').value = d.initial;
    updateDirty();
    setStatus('saved to manual');
    render();
    refreshListRow(d);
  }catch(e){ setStatus(String(e.message || e), true); }
}
function refreshListRow(d){
  const rec = ROWS.find(r => r[0] === d.rel && r[2] === d.pos);
  if(!rec) return;
  rec[3] = d.initial;
  rec[4] = d.state;
  rec[5] = (d.man && d.man.note) || '';
  rec[6] = d.man ? 1 : 0;
  if(MODE !== 'rows') return;
  const el = ROW_EL.get(keyOf(rec));
  if(el) el.innerHTML = rowHtml(rec);
}

// ---- psp matches for this row: the "find psp" button ----
// Not a watcher: nothing is searched until the button is pressed, and what is
// searched is the text in the editor right now (a draft included).
let MATCH = [], MATCHQ = 0;
function clearMatches(){
  MATCH = [];
  $('matches').innerHTML = '';
  $('matchstat').textContent = "search the PSP-US + PSP-JP text for this row's wording";
}
function likClass(l){ return l >= .7 ? '' : (l >= .4 ? 'mid' : 'low'); }
function matchHtml(h, i){
  const pct = Math.round(h.lik * 100);
  const chips = h.matched.length
    ? h.matched.map(m => `<span class="chip">${esc(m)}</span>`).join('')
    : '<span class="chip none">nothing distinctive matched</span>';
  const flags = h.flags && h.flags.length
    ? `<div class="flags">${esc(h.flags.join(' · '))}</div>` : '';
  return `<div class="mcard" data-i="${i}">` +
    `<div class="mk"><span class="tag ${h.region}">PSP ${h.region.toUpperCase()}</span>` +
    `<span class="fam">${esc(h.rel)}</span> #${esc(h.id)}` +
    `<span class="pg"> · ${esc(h.pos)}</span><span class="lik">${pct}%</span></div>` +
    `<div class="bar ${likClass(h.lik)}"><i style="width:${pct}%"></i></div>` +
    `<div class="mt">${esc(h.text)}</div>` +
    `<div class="chips">${chips}</div>${flags}` +
    `<div class="mbtns"><button class="btn" data-act="open">open unit</button>` +
    `<button class="btn" data-act="import">import as draft</button></div></div>`;
}
function renderMatches(d){
  MATCH = d.hits;
  $('matches').innerHTML = d.hits.map(matchHtml).join('');
  $('matchstat').textContent = d.hits.length
    ? `${d.hits.length} candidate${d.hits.length === 1 ? '' : 's'} · ` +
      `looked for ${d.needles.length} distinctive piece${d.needles.length === 1 ? '' : 's'}`
    : 'nothing in either extract matched this text';
}
async function findMatches(){
  if(!CUR){ setStatus('pick a row first', true); return; }
  const seq = ++MATCHQ;
  $('matchstat').textContent = 'searching…';
  const q = 'rel=' + encodeURIComponent(CUR.rel) +
            '&pos=' + encodeURIComponent(CUR.pos) +
            '&text=' + encodeURIComponent($('src').value) + '&limit=12';
  try{
    const r = await fetch('/match?' + q);
    const d = await r.json();
    if(seq !== MATCHQ) return;
    if(!r.ok) throw new Error(d.error || 'search failed');
    renderMatches(d);
  }catch(e){
    if(seq === MATCHQ) $('matchstat').textContent = String(e.message || e);
  }
}
function importHit(h){
  $('src').value = h.import_text;
  DIRTY = true;
  updateDirty();
  render();
  const warn = h.flags && h.flags.length ? ' · ' + h.flags.join(', ') : '';
  setStatus(`imported PSP ${h.region.toUpperCase()} ${h.rel} #${h.id} — not saved${warn}`,
            !!(h.flags && h.flags.length));
}
$('matches').onclick = e => {
  const btn = e.target && e.target.closest && e.target.closest('[data-act]');
  if(!btn) return;
  const card = btn.closest('.mcard');
  const h = MATCH[+(card && card.dataset.i)];
  if(!h) return;
  if(btn.dataset.act === 'import') importHit(h);
  else showRefFor([h.region, h.rel, h.id, h.pos, h.text]);
};

// ---- PSP text search: US + JP, with the aligned twin ----
function showRef(u){
  REF = u;
  const box = $('ref');
  box.hidden = false;
  const line = (x, cur) => `<div class="unit${cur ? ' cur' : ''}">` +
    `<span class="pk">#${esc(x[0])}</span><span class="pv">${esc(x[2])}</span></div>`;
  let html = `<div><span class="tag ${u.region}">PSP ${u.region.toUpperCase()}</span> ` +
             `<span class="k">${esc(u.rel)} #${esc(u.id)} · ${esc(u.pos)}</span></div>`;
  html += u.prev.map(x => line(x, false)).join('');
  html += line([u.id, u.pos, u.text], true);
  html += u.next.map(x => line(x, false)).join('');
  if(u.twin){
    html += `<div class="twinhead">PSP ${u.twin.region.toUpperCase()} · same unit</div>` +
            line([u.twin.id, u.twin.pos, u.twin.text], false);
  }
  html += `<div class="refbtns">` +
          (CUR ? '<button class="btn" id="useref">use as draft</button>' : '') +
          '<button class="btn" id="copyref">copy text</button>' +
          '<button class="btn" id="closeref">close</button></div>';
  box.innerHTML = html;
  const use = $('useref');
  if(use) use.onclick = () => { $('src').value = u.text; DIRTY = true; updateDirty(); render(); };
  $('copyref').onclick = () => copyText(u.text);
  $('closeref').onclick = () => { box.hidden = true; REF = null; };
  if(box.scrollIntoView) box.scrollIntoView({block: 'nearest'});
}
async function showRefFor(h){
  try{
    const r = await fetch(`/psp/unit?region=${encodeURIComponent(h[0])}` +
                          `&rel=${encodeURIComponent(h[1])}&id=${encodeURIComponent(h[2])}`);
    if(!r.ok) throw new Error('unit not found');
    showRef(await r.json());
  }catch(e){ setStatus(String(e.message || e), true); }
}
let SEARCH_T = null;
function onFilter(){
  const q = $('filt').value.trim();
  clearTimeout(SEARCH_T);
  if(MODE === 'rows'){
    SHOWN = matches(q);
    renderList();
    return;
  }
  if(!q){
    HITS = []; SHOWN = []; renderList();
    return;
  }
  SEARCH_T = setTimeout(() => runSearch(q), 160);
}
async function runSearch(q){
  const seq = ++HITSEQ;
  try{
    const r = await fetch(`/psp?q=${encodeURIComponent(q)}&limit=300`);
    if(!r.ok) throw new Error('search failed');
    const hits = await r.json();
    if(seq !== HITSEQ) return;
    HITS = hits; SHOWN = hits;
    renderList();
  }catch(e){ if(seq === HITSEQ) setStatus(String(e.message || e), true); }
}
function setMode(m){
  MODE = m;
  for(const b of document.querySelectorAll('.mode')) b.classList.toggle('on', b.dataset.mode === m);
  $('fam').style.display = m === 'rows' ? '' : 'none';
  $('manfilt').style.display = m === 'rows' ? '' : 'none';
  const f = $('filt');
  f.value = '';
  f.placeholder = m === 'rows' ? 'filter rows…' : 'search PSP US + JP text…';
  HITS = []; SHOWN = m === 'rows' ? matches('') : [];
  renderList();
}

// ---- navigation ----
async function stepRow(step){
  if(!SHOWN.length) return;
  if(MODE === 'rows'){
    const cur = CUR ? SHOWN.findIndex(r => r[0] === CUR.rel && r[2] === CUR.pos) : -1;
    const i = Math.max(0, Math.min(SHOWN.length - 1, cur + step));
    await pick(SHOWN[i]);
    scrollRowIntoView(i);
  } else {
    const cur = REF ? SHOWN.findIndex(h => h[0] === REF.region && h[1] === REF.rel &&
                                           String(h[2]) === String(REF.id)) : -1;
    const i = Math.max(0, Math.min(SHOWN.length - 1, cur + step));
    await showRefFor(SHOWN[i]);
    scrollRowIntoView(i);
  }
}
function copyText(t){
  if(navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(t).then(() => setStatus('copied'), () => setStatus('copy failed', true));
  } else {
    setStatus('copy failed', true);
  }
}

// ---- wiring ----
// the sidebar paints in chunks; reaching the end paints the next one
$('list').onscroll = () => {
  const l = $('list');
  if(l.scrollTop + l.clientHeight > l.scrollHeight - 400) appendRows();
};
$('filt').oninput = onFilter;
$('filt').onkeydown = e => {
  if(e.key === 'Enter' && SHOWN.length){
    MODE === 'rows' ? pick(SHOWN[0]) : showRefFor(SHOWN[0]);
    return;
  }
  const step = {'ArrowDown': 1, 'ArrowRight': 1, 'ArrowUp': -1, 'ArrowLeft': -1}[e.key];
  if(!step) return;
  e.preventDefault();
  stepRow(step);
};
$('fam').onchange = e => { FAM = e.target.value; if(MODE === 'rows'){ SHOWN = matches($('filt').value.trim()); renderList(); } };
$('manfilt').onchange = e => { MANF = e.target.value; if(MODE === 'rows'){ SHOWN = matches($('filt').value.trim()); renderList(); } };
$('longonly').onchange = () => { if(MODE === 'rows'){ SHOWN = matches($('filt').value.trim()); renderList(); } };
for(const b of document.querySelectorAll('.mode')) b.onclick = () => setMode(b.dataset.mode);
$('save').onclick = saveDraft;
$('find').onclick = findMatches;
$('copy').onclick = () => { if(CUR) copyText(`${CUR.rel} ${CUR.pos}`); };
$('copyt').onclick = () => { if(CUR) copyText(CUR.initial); };
const srcEl = $('src');
srcEl.oninput = () => { DIRTY = true; updateDirty(); render(); };
// a picked row is one TSV line: a break is a code, not a newline (typed
// no-row text keeps Enter - that is the flow-layout demo)
srcEl.onkeydown = e => {
  if(CUR && e.key === 'Enter' && !e.ctrlKey && !e.metaKey){
    e.preventDefault();
    setStatus('one row is one line — type <FF03> (dialogue) or <FFF6> (battle) for a break', true);
  }
};
document.addEventListener('keydown', e => {
  if((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === 's'){
    e.preventDefault();
    saveDraft();
    return;
  }
  const tag = (document.activeElement && document.activeElement.tagName) || '';
  if(tag === 'TEXTAREA' || tag === 'INPUT' || tag === 'SELECT') return;
  const step = {'ArrowDown': 1, 'ArrowRight': 1, 'ArrowUp': -1, 'ArrowLeft': -1}[e.key];
  if(!step) return;
  e.preventDefault();
  stepRow(step);
});
window.addEventListener('beforeunload', e => { if(DIRTY){ e.preventDefault(); e.returnValue = ''; } });
for(const id of ['zoom', 'shadow', 'guides']) $(id).oninput = render;

// ---- boot ----
function loadRows(){
  return fetch('/rows?limit=100000').then(r => r.ok ? r.json() : Promise.reject())
    .catch(() => fetch('rows.json').then(r => r.json()))
    .then(d => { ROWS = d; fillFamilies(); SHOWN = matches(''); renderList(); })
    .catch(() => { ROWS = []; fillFamilies(); SHOWN = []; renderList(); });
}
loadFont();
loadRows();
updateDirty();
render();
