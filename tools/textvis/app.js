'use strict';
// ---- the real font: /font reads the build's vwf_font.bin + vwf_width.bin,
// plus the retail Japanese FONT.BIN and its glyph map, which draws every
// character the English font has no cell for. The baked copy below is only
// what a file:// open (no server) falls back to.
const WIDTH_FALLBACK="BAQHCQEHCAQFBQgHBAcECAgGCAgIBwgICAgEBAcICAkBCAgICAgICAgECAgICAkICAgJCAgJCAgICAgBCAEBAQYICAcIBwYICAQFCAQIBwcICAcHBggICAgIBwYFBggJAQg=";
const FONT_FALLBACK="AAAAAAAAAAAAAAAAAAAAAGBgYGBgYGBgYABgYAAAAABsbCRIAAAAAAAAAAAAAAAAABISEv8kJCT/SEhIAAAAAAAAAAAAAAAAAAAAAAAAAABEpKhIEBAgIEhUlIgAAAAAIFCIUCBehISEhEoyAAAAAGBgIEAAAAAAAAAAAAAAAAAQIEBAQEBAQEBAIBAAAAAAQCAQEBAQEBAQECBAAAAAAAAAAJJUOP44VJIAAAAAAAAAAAAAEBB8EBAAAAAAAAAAAAAAAAAAAAAAAGBgIEAAAAAAAAAAAHwAAAAAAAAAAAAAAAAAAAAAAAAAYGAAAAAAAgIEBAgIEBAgIEBAAAAAADhEioqSkpKSoqJEOAAAAAAgIOAgICAgICAgIPgAAAAAOESCAgQIECBAgIL+AAAAADhEAgIEOAQCAgKEeAAAAAAICBgoKEhI/ggICBwAAAAA+ICAgIDwCAQEBIhwAAAAADhEgoCAuMSCgoJEOAAAAAD+ggIECAgQECAgQEAAAAAAOESCgkQ4RIKCgkQ4AAAAADhEgoKCRjoCAoJEOAAAAAAAAABgYAAAAAAAYGAAAAAAAAAAYGAAAAAAAGBgIEAAAAAABAgQIEAgEAgEAAAAAAAAAAAAfgAAfgAAAAAAAAAAAAAgEAgEAgQIECAAAAAAABw+Z0MDBgwYGAAYGAAAAAAAAAAAAAAAAAAAAAAAAAAAECgoRER8RERERETuAAAAAPBIREREeERCQkJC/AAAAAA6RoKAgICAgICCQjwAAAAA8EhEQkJCQkJCQkT4AAAAAP5CQEBAeEBAQEBC/gAAAAD+QkBAQHhAQEBAQOAAAAAAOkaCgICOgoKCgkY6AAAAAO5EREREfERERERE7gAAAADgQEBAQEBAQEBAQOAAAAAAPggICAgICAgIiIhwAAAAAOZESEhQYFBISERE5gAAAADgQEBAQEBAQEBAQv4AAAAAxmxsbFRUVFRERETuAAAAAMdCYmJSUkpKRkZC4gAAAAA4RIKCgoKCgoKCRDgAAAAA2GRCQkJEeEBAQEDgAAAAADhEgoKCgoKCkopEOgAAAADYZEJCQkR4REJCQuMAAAAAOkaCgEA4BAKCgsS4AAAAAP6SEBAQEBAQEBAQOAAAAADnQkJCQkJCQkJCQjwAAAAA7kREREQoKCgoEBAQAAAAAO5EREREVFRUVCgoKAAAAADuREQoKBAoKChERO4AAAAA7kREKCgQEBAQEBA4AAAAAP6CBAQIEBAgQECC/gAAAAAAAAAAAAAAAAAAAAAAAAAAQEAgIBAQCAgEBAICAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEAgEAgAAAAAAAAAAAAAAAAAAAAAADhEBHyEjHYAAAAAwEBAQEBYZEJCQmLcAAAAAAAAAAAANEyAgIBEOAAAAAAMBAQEBDRMhISETDYAAAAAAAAAAAAwSIT8gEQ4AAAAAAAwSEBA8EBAQEBA4AAAAAAAAAAAADZMhISETDQEhHgAwEBAQEB4RERERETuAAAAAAAAAEAAwEBAQEBA4AAAAAAAAAAQADAQEBAQEBCQkGAAwEBAQERIUGBQSETmAAAAAMBAQEBAQEBAQEBA4AAAAAAAAAAAAKhUVFRUVNYAAAAAAAAAAACwSEhISEjsAAAAAAAAAAAAMEiEhIRIMAAAAAAAAAAAANhkQkJCZFhAQOAAAAAAAAA2TISEhEw0BAQOAAAAAAAAuERAQEBA4AAAAAAAAAAAAHiEgHgEhHgAAAAAAAAAQEDwQEBAQEgwAAAAAAAAAAAAzEREREREOgAAAAAAAAAAAO5ERCgoEBAAAAAAAAAAAADuRERUVCgoAAAAAAAAAAAA7kQoEChE7gAAAAAAAAAAAO5ERCgoEBAgwAAAAAAAAAD8hAgwQIT8AAAAABggICAgQCAgICAgGAAAAAAQEBAQEBAQEBAQEBAAAAAAYBAQEBAIEBAQEBBgAAAAAAAAAAAiVIgAAAAAAAAAAAAAAAAAAAAAAAAA29sAAAAAAAAAAAAAAAAAAAAAAAAAAO5ERCgoEHwQfBAQOAAAAAA=";
let ADV=Uint8Array.from(atob(WIDTH_FALLBACK),c=>c.charCodeAt(0));
let FONT=Uint8Array.from(atob(FONT_FALLBACK),c=>c.charCodeAt(0));
let ORIG=null, GMAP={};
// THE FONT EDITION (docs/TEXT_LAYOUT_SPEC.md, "Font editions"): large, small,
// or both - the large edition drawn as usual and the small one under it.
// A row carries every edition's layout (<LFF03> breaks only in large,
// <SFF03> only in small, <L{>...<}> / <S{>...<}> wording one edition alone
// has); editionText reads one edition back, as vwf_wrap.edition_text does.
let EDITION='large';
try{ EDITION=localStorage.getItem('textvis.edition')||'large'; }catch(e){}
const primaryEdition=()=>EDITION==='both'?'large':EDITION;
function editionText(s, edition){
  if(!s||(s.indexOf('<L')<0&&s.indexOf('<S')<0)) return s;
  const letter=edition==='small'?'S':'L';
  s=s.replace(/<([LS])\{>([\s\S]*?)<\}>/g,(m,l,t)=>l===letter?t:'');
  return s.replace(/(?:<[LS][0-9A-F]{2,4}>)+/g,(run,off,all)=>{
    const own=(run.match(/<([LS])([0-9A-F]{2,4})>/g)||[])
      .filter(c=>c[1]===letter).map(c=>'<'+c.slice(2)).join('');
    if(own) return own;
    const before=all[off-1], after=all[off+run.length];
    return (before&&before!==' '&&before!=='>'&&after&&after!==' '&&after!=='<')?' ':'';
  });
}
// each edition's glyphs and advances (the page draws a choice grid itself,
// in every edition it shows); useFont makes one the current face
const FONTS={};
function useFont(edition){
  const f=FONTS[edition]||FALLBACK;
  ADV=f.adv; FONT=f.font; EXTRA=f.extra; SPELL=f.spell; CUSTOM=f.custom||{};
}
function loadFont(){
  const want=EDITION==='both'?['large','small']:[primaryEdition()];
  return Promise.all(want.map(ed=>fetch('/font?edition='+ed).then(r=>r.ok?r.json():Promise.reject())
    .then(d=>{FONTS[ed]={adv:Uint8Array.from(atob(d.widths),c=>c.charCodeAt(0)),
                         font:Uint8Array.from(atob(d.font),c=>c.charCodeAt(0)),
                         extra:d.extra, custom:d.custom, spell:d.spell, sheetError:d.sheet_error};
              if(d.orig){
                ORIG=Uint8Array.from(atob(d.orig),c=>c.charCodeAt(0));
                GMAP=d.map||{};
              }})))
    .then(()=>{
      useFont(primaryEdition());
      document.getElementById('edition').title=FONTS[primaryEdition()]?.sheetError||'';
      render();
    })
    .catch(()=>{});
}
const BOX=239, SCROLL_ROWS=3;
const FALLBACK={adv:ADV, font:FONT, extra:{'…':0x7F,'❤':0x80,'￥':0x81},
                spell:{'＊':'*','’':"'",'‘':"'",'“':'"','”':'"','–':'-','—':'-','−':'-','＞':'>','＜':'<'}};
let {extra:EXTRA, spell:SPELL}=FALLBACK;
let CUSTOM={};
function fold(ch){return SPELL[ch]||ch}
function code(ch){const c=fold(ch);const o=c.codePointAt(0);
  if(o>=0x20&&o<=0x7E)return o;
  if(EXTRA[c]!==undefined)return EXTRA[c];
  return null}
function cw(ch){const custom=CUSTOM[fold(ch)]; if(custom)return custom[0];
  const k=code(ch);return k===null?16:ADV[k-0x20]}
// control codes and their parameter bytes (a name insert's あ, <FFFD>'s
// branch character - "ヌ" in the demon lines) never print and never measure.
const CODE_PARAM=/<FFFD>.|<FF(07|08|0F)>あ|<[^>]+>/g;
// THE TEXT AS THE FILE HAS IT, with the codes made readable instead of
// deleted: `\n` is a line break, `␌` a new box, `⏸` a wait, `{name}` the
// player's name slot. The list preview uses it; the editor and the sources
// show the literal codes.
function pretty(s){
  return editionText(s, primaryEdition())
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
// what the box really shows for one stored line: the player's name stands in
// as {name} (8 glyphs, the entry's cap), every other code is invisible
function drawText(s){
  return withPlaceholder(s).replace(/<FFFD>./g, '').replace(/<[^>]+>/g, '');
}

// ---- choice grids (ADV <FF0E> option blocks) ----
// The TSV spells a choice as grid rows joined by <FF03>, with `|` between the
// cells of a two-column row. choices.layout puts column 2 at the nearest 16 px
// stop that clears column 1 by 4 px and keeps the whole row inside 239 px.
// Four options are only ever a 2x2 grid: the message box is three 16 px rows
// and the prompt's arming line is the first, leaving two for the options.
const CHOICE_PX=239, CHOICE_OPTION_ROWS=2;
function choiceCells(text){
  return text.replace(/<FF01>|<FFEF>|<FFF5>/g,'').split('<FF03>')
             .map(l=>l.split('|'));
}
function choiceFit(cells, wantWidth){
  const rows=cells.length, cols=Math.max(...cells.map(r=>r.length));
  const out={rows, cols, width:null, x2:0, need:0,
             widths:cells.map(r=>r.map(c=>textWidth(c)))};
  if(cols===2){
    const cands=[]; for(let w=0;w<15;w++) cands.push(w);
    cands.sort((a,b)=>Math.abs(a-wantWidth)-Math.abs(b-wantWidth)||a-b);
    for(const w of cands){
      const x2=(w+1)*16;
      if(out.widths.every(([w1,w2])=>x2>=w1+4 && x2+w2<=CHOICE_PX)){
        out.width=w; out.x2=x2;
        return out;
      }
    }
    for(const [w1,w2] of out.widths)
      out.need=Math.max(out.need, Math.ceil((w1+4)/16)*16+w2);
    // no legal stop: still draw the columns far enough apart to read
    out.x2=Math.max(...out.widths.map(([w1])=>Math.ceil((w1+4)/16)*16));
    return out;
  }
  out.need=Math.max(0,...out.widths.map(([w1])=>w1));
  return out;
}
function choiceViolations(fit, meta, cells){
  const v=[];
  const shapeOk = fit.rows===meta.rows && fit.cols===meta.cols &&
                  cells.every(r=>r.length===meta.cols);
  if(fit.rows!==meta.rows || fit.cols!==meta.cols)
    v.push(`grid is ${fit.rows}x${fit.cols}, the table is ${meta.rows}x${meta.cols}`);
  // choices.layout asserts this exact shape (rows of <FF03>, cells of |), so
  // a missing or extra cell is a build failure, not just a drawing oddity.
  cells.forEach((r,i)=>{
    if(r.length!==meta.cols)
      v.push(`row ${i+1} has ${r.length} cell(s), expected ${meta.cols}`);
  });
  if(shapeOk){
    if(fit.cols===2 && fit.width===null)
      v.push(`no 2-column stop fits: needs ${fit.need}px/${CHOICE_PX}px`);
    if(fit.rows>CHOICE_OPTION_ROWS)
      v.push(`${fit.rows} option rows; the box shows ${CHOICE_OPTION_ROWS}`);
    if(fit.cols===1){
      const wide=fit.widths.flat().filter(w=>w>224);
      if(wide.length) v.push(`option is ${Math.max(...wide)}px (224px max)`);
    }
  }
  return v;
}

// ---- drawing the real font ----
const cv=document.getElementById('cv');
let ctx=cv.getContext('2d');      // the canvas being drawn (renderChoice may switch it)
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
  const custom=CUSTOM[fold(ch)];
  if(k===null&&!custom)return drawOrig(ch,x,y,z,color);
  const adv=custom?custom[0]:ADV[k-0x20];
  ctx.fillStyle=color;
  for(let r=0;r<16;r++){const bits=custom?custom[1][r]:FONT[(k-0x20)*16+r];
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
function renderChoice(text, z, shadow, guides, canvas=cv, quiet=false){
  // The choice row is only the option block: the prompt (and its arming
  // <FF03><FF0E>) is the row above, drawn here as the box's first line so the
  // options start where the engine's cursor does (row*16 + 0xB4). `canvas`
  // and the current face (useFont) pick where and in which edition; a
  // `quiet` draw (the second edition) leaves the line table and status alone.
  ctx=canvas.getContext('2d');
  try{ drawChoice(text, z, shadow, guides, canvas, quiet); }
  finally{ ctx=cv.getContext('2d'); }
}
function drawChoice(text, z, shadow, guides, canvas, quiet){
  const meta=CUR.choice;
  const cells=choiceCells(text);
  const fit=choiceFit(cells, meta.width||0);
  const PADX=4, PADY=6, ROWS=3;
  const shown=Math.max(ROWS, 1+fit.rows);
  const W=(BOX+16)*z, H=(shown*16+PADY*2)*z;
  canvas.width=W; canvas.height=H; canvas.style.width=W+'px'; canvas.style.height=H+'px';
  const wrap=document.getElementById('cvwrap');
  if(!quiet && wrap && wrap.style) wrap.style.minHeight=(H+2)+'px';
  ctx.clearRect(0,0,W,H);
  ctx.fillStyle='#0b1a10'; ctx.fillRect(0,0,W,H);
  if(guides){
    ctx.fillStyle='rgba(255,255,255,.06)';
    for(let r=0;r<shown;r++) ctx.fillRect(0,(PADY+r*16)*z,W,1);
    ctx.fillStyle='rgba(255,255,255,.12)';
    ctx.fillRect((PADX+BOX)*z,0,1,(ROWS*16+PADY*2)*z);
    // the box's bottom edge: anything below is the engine's scroll
    ctx.fillStyle='rgba(255,255,255,.18)';
    ctx.fillRect(0,(PADY+ROWS*16)*z,W,1);
  }
  drawLine('prompt', PADX*z, PADY*z, z, 'rgba(232,193,90,.30)', false);
  const rows=[];
  fit.widths.forEach((ws,i)=>{
    const y=(PADY+(1+i)*16)*z;
    ws.forEach((w,c)=>{
      const cell=cells[i][c];
      const dx=c===0?0:(c===1?fit.x2:fit.x2+(c-1)*80);
      drawLine(drawText(cell), (PADX+dx)*z, y, z,
               i<CHOICE_OPTION_ROWS?'#dfe7df':'rgba(223,231,223,.42)', shadow);
      // a cell's number is where its glyphs END: column 2 starts at the grid
      // stop, so its own width alone never proves the row fits the box.
      const end=c===0?w:fit.x2+w;
      const cap=fit.cols===1?224:CHOICE_PX;
      rows.push([`${i+1}.${c+1}`, end, cell, end>cap]);
    });
  });
  if(quiet) return;
  const tb=document.getElementById('lines'); tb.innerHTML='';
  for(const [tag,w,l,over] of rows){
    tb.insertAdjacentHTML('beforeend',
      `<tr><td class="w">${tag}</td>`+
      `<td class="w ${over?'warn':''}">${Math.round(w)}</td>`+
      `<td>${esc(l)}</td></tr>`);
  }
  const viol=choiceViolations(fit, meta, cells);
  document.getElementById('stat').innerHTML=
    `<span class="${viol.length?'warn':'ok'}">${viol.length?viol.join(' · '):'choice grid fits'}</span>`+
    ` · ${fit.rows} option row(s) · ${fit.cols} column(s)`+
    (fit.width!==null?` · col2 at ${fit.x2}px`:'');
}
// ---- the box: drawn by the server's model of the game ----
// /render runs the porter's own code: vwf_render (the compositor in
// vwf_dialog_draw.asm: ink, the +1,+1 shadow on rows 0-14, the 240 px clip,
// the engine's own wrap, inserts at their priced width) and
// vwf_wrap.shape_report (the findings the flow scores with). Nothing here
// knows a wrapping rule, so the page can never disagree with the port.
const INK_RGB=[0xdf,0xe7,0xdf,255], SHADE_RGB=[0,0,0,255], INSERT_RGB=[232,193,90,140], BG='#0b1a10';
const PAD=6, GAP=10, SHOWN_ROWS=3;
let RSEQ=0, RT=null;
function render(){
  const text=$('src').value;
  const z=Math.max(1, Math.round(+$('zoom').value));
  if(CUR && CUR.choice){
    $('headwrap').hidden=true; $('nowhead').hidden=true; $('wdiff').hidden=true;
    for(const el of document.querySelectorAll('.small-ed')) el.hidden = EDITION!=='both';
    renderChoice(editionText(text, primaryEdition()), z, $('shadow').checked, $('guides').checked);
    // both editions: the small grid under the large one, in its own face
    if(EDITION==='both' && FONTS.small){
      useFont('small');
      try{ renderChoice(editionText(text, 'small'), z, $('shadow').checked, $('guides').checked, $('cv2'), true); }
      finally{ useFont(primaryEdition()); }
    }
    return;
  }
  clearTimeout(RT);
  RT=setTimeout(()=>renderServer(text), 150);
}
async function fetchRender(text, flow, weigh=true, edition=primaryEdition()){
  const r=await fetch('/render',{method:'POST',headers:{'Content-Type':'application/json'},
                                 body:JSON.stringify({rel:CUR?CUR.rel:'', text, flow, weigh, edition})});
  const d=await r.json();
  if(!r.ok) throw new Error(d.error||'render failed');
  return d;
}
function drawPages(canvas, d, zoom, shadow, guides){
  // drawn at the game's own 1x and scaled by CSS (image-rendering: pixelated)
  const z=1;
  const c=canvas.getContext('2d');
  const box=d.box, W=(box+PAD*2)*z;
  const hs=d.pages.map(p=>Math.max(p.h, SHOWN_ROWS)*16);
  const H=Math.max(1, hs.reduce((a,h)=>a+(h+PAD*2+GAP)*z, 0));
  canvas.width=W; canvas.height=H;
  canvas.style.width=(W*zoom)+'px'; canvas.style.height=(H*zoom)+'px';
  c.fillStyle=BG; c.fillRect(0,0,W,H);
  let base=0;
  d.pages.forEach((p,pi)=>{
    const px=Uint8Array.from(atob(p.planes), ch=>ch.charCodeAt(0));
    const ox=PAD*z, oy=base+PAD*z;
    if(guides){
      c.fillStyle='rgba(255,255,255,.06)';
      for(let r=0;r<=Math.max(p.h,SHOWN_ROWS);r++) c.fillRect(0, oy+r*16*z, W, 1);
      c.fillStyle='rgba(255,255,255,.18)';
      c.fillRect(ox+box*z, base, 1, (hs[pi]+PAD*2)*z);       // the 240 px edge
      c.fillStyle='rgba(255,255,255,.08)';
      c.fillRect(ox+(box-1)*z, base, 1, (hs[pi]+PAD*2)*z);   // 239: the line limit
    }
    // one pixel per pixel into an ImageData, scaled up once (no per-pixel
    // canvas calls); the rows past the box's three are what it scrolls to
    if(p.h){
      const img=new ImageData(box, p.h*16), a=img.data;
      for(let y=0;y<p.h*16;y++){
        const dim=(y>>4)>=SHOWN_ROWS;
        for(let x=0;x<box;x++){
          const v=px[y*box+x];
          let col=null;
          if(v&1) col=INK_RGB; else if(v&4) col=INSERT_RGB; else if((v&2)&&shadow) col=SHADE_RGB;
          if(!col) continue;
          const o=(y*box+x)*4;
          a[o]=col[0]; a[o+1]=col[1]; a[o+2]=col[2]; a[o+3]=dim?107:col[3];
        }
      }
      const off=document.createElement('canvas'); off.width=box; off.height=p.h*16;
      off.getContext('2d').putImageData(img,0,0);
      c.imageSmoothingEnabled=false;
      c.drawImage(off, ox, oy, box*z, p.h*16*z);
    }
    base+=(hs[pi]+PAD*2+GAP)*z;
    if(guides && pi+1<d.pages.length){
      c.fillStyle='rgba(255,255,255,.18)'; c.fillRect(0, base-GAP/2*z, W, 1);
    }
  });
}
// THE CLOSE CALLS: per box, the layout the flow nearly chose (vwf_wrap.weigh)
// when it lost on line ends + shape by under a point, and the flow's own
// choice when the stored lines are not it (a manual row, or a table the rules
// moved on from). Each is drawn so the two can be compared by eye.
async function showWeigh(d, z, shadow, guides, seq){
  const box=$('weigh'); box.innerHTML=''; box.hidden=true;
  const brk=/<FFF6>/.test($('src').value)?'<FFF6>':'<FF03>';
  for(const [pi,p] of d.pages.entries()) for(const w of p.weighs){
    if(!w) continue;
    const shows=[];
    if(w.stored_differs) shows.push([`box ${pi+1}: the flow now lays this out differently`, w.chosen]);
    if(w.close) shows.push([`box ${pi+1}: close call — ${marginText(w.margin)} on ${esc(w.decided_by)}`, w.runner_up]);
    for(const [label, lines] of shows){
      box.hidden=false;
      box.insertAdjacentHTML('beforeend', `<div class="wk">${label}</div>`);
      const c=document.createElement('canvas'); box.appendChild(c);
      const cp=document.createElement('button');
      cp.className='btn'; cp.textContent='copy lines';
      cp.title='this layout as lines with widths, with the stored one above it';
      cp.style.alignSelf='flex-start';
      box.appendChild(cp);
      try{
        const r=await fetchRender(lines.join(brk), false, false);
        if(seq!==RSEQ) return;
        drawPages(c, r, z, shadow, guides);
        cp.onclick=()=>copyText(`${rowHead()}\n${LAST_NOW?linesText(LAST_NOW)+'\n':''}`+
                                `${label.replace(/<[^>]+>/g,'')}:\n${linesText(r)}`);
      }catch(e){ cp.remove(); }
    }
  }
}
function wordDiff(a, b){
  const ta=a.split(/(\s+|<[^>]+>)/).filter(x=>x), tb=b.split(/(\s+|<[^>]+>)/).filter(x=>x);
  const n=ta.length, m=tb.length;
  if(n*m>400000) return esc(b);
  // a WORD outweighs a space or a code in the alignment: when only a line
  // break moved ("Did you<FF03>really" -> "Did you really<FF03>"), the words
  // stay matched and the break shows as moved - never the word struck on one
  // side of it and inserted on the other
  const wt=t=>/^(\s+|<[^>]+>)$/.test(t)?1:3;
  const L=[...Array(n+1)].map(()=>new Uint32Array(m+1));
  for(let i=n-1;i>=0;i--) for(let j=m-1;j>=0;j--)
    L[i][j]=ta[i]===tb[j]?L[i+1][j+1]+wt(ta[i]):Math.max(L[i+1][j],L[i][j+1]);
  let i=0,j=0,out='';
  while(i<n||j<m){
    if(i<n&&j<m&&ta[i]===tb[j]&&L[i][j]===L[i+1][j+1]+wt(ta[i])){out+=esc(ta[i]);i++;j++;}
    else if(j<m&&(i>=n||L[i][j+1]>=L[i+1][j])){out+='<ins>'+esc(tb[j])+'</ins>';j++;}
    else {out+='<del>'+esc(ta[i])+'</del>';i++;}
  }
  return out;
}
// THE LAST RENDERS, for the copy buttons: what the box shows now and at HEAD
let LAST_NOW=null, LAST_HEAD=null;
function linesText(d){
  return d.pages.map((p,pi)=>p.lines.map((l,li)=>
    `${String(l.width).padStart(4)}  ${pi+1}.${li+1}${li>=SHOWN_ROWS?'↕':' '} ${l.text}`).join('\n')).join('\n  --\n');
}
function rowHead(){
  if(!CUR) return '(typed text)';
  const id=(CUR.gen&&CUR.gen.id)||(CUR.man&&CUR.man.id)||'';
  return `${CUR.rel} #${id} · pos ${CUR.pos}`;
}
async function renderServer(text){
  const seq=++RSEQ;
  const z=Math.max(1, Math.round(+$('zoom').value));
  const shadow=$('shadow').checked, guides=$('guides').checked;
  let d;
  try{ d=await fetchRender(text, !CUR, false); }
  catch(e){ if(seq===RSEQ) $('stat').innerHTML=`<span class="warn">${esc(e.message||e)}</span>`; return; }
  if(seq!==RSEQ) return;
  LAST_NOW=d; LAST_HEAD=null;
  drawPages(cv, d, z, shadow, guides);
  // both editions: the small one under the large one, in each column (HEAD
  // and now), from the same text
  for(const el of document.querySelectorAll('.small-ed')) el.hidden = EDITION!=='both';
  if(EDITION==='both'){
    fetchRender(text, !CUR, false, 'small')
      .then(o=>{ if(seq===RSEQ) drawPages($('cv2'), o, z, shadow, guides); }).catch(()=>{});
  }
  const wrap=$('cvwrap'); if(wrap && wrap.style) wrap.style.minHeight=(cv.height*z+2)+'px';
  const tb=$('lines'); tb.innerHTML='';
  const found=[], notes=[];
  d.pages.forEach((p,pi)=>{
    p.lines.forEach((l,li)=>{
      const over=l.width>240||l.engine_wraps>0;
      tb.insertAdjacentHTML('beforeend',
        `<tr><td class="${li>=SHOWN_ROWS?'pg':'w'}">${pi+1}.${li+1}</td>`+
        `<td class="w ${over?'warn':''}">${l.width}${l.engine_wraps?' ↵':''}</td>`+
        `<td class="${li>=SHOWN_ROWS?'pg':''}">${esc(l.text)}</td></tr>`);
      if(l.engine_wraps) found.push(`box ${pi+1} line ${li+1}: the engine wraps it`);
    });
    // a scroll is no fault (a wait then a line move): said, not flagged
    if(p.lines.length>SHOWN_ROWS) notes.push(`box ${pi+1} scrolls (${p.lines.length} lines)`);
    if(p.findings.length) found.push(`box ${pi+1}: ${p.findings.join(', ')}`);
    if(p.missing.length) found.push(`box ${pi+1}: no glyph for ${p.missing.join(' ')}`);
  });
  $('stat').innerHTML=`<span class="${found.length?'warn':'ok'}">${found.length?esc(found.join(' · ')):'no finding'}</span>`+
    ` · ${d.pages.reduce((a,p)=>a+p.lines.length,0)} lines · ${d.pages.length} box(es)`+
    (notes.length?` · ${esc(notes.join(' · '))}`:'');
  // the close calls cost the server a weighing: the box is drawn first and
  // the panel follows from a second, weighed render of the same text
  fetchRender(text, !CUR, true).then(w=>{ if(seq===RSEQ) showWeigh(w, z, shadow, guides, seq); }).catch(()=>{});
  // side by side: what HEAD ships on the left, the working tree on the right
  const hw=$('headwrap'), show=on=>{ hw.hidden=!on; $('nowhead').hidden=!on; $('wdiff').hidden=!on; };
  if(CUR && CUR.head!=null && CUR.head!==text){
    let h;
    try{ h=await fetchRender(CUR.head, false, false); }catch(e){ show(false); return; }
    if(seq!==RSEQ) return;
    show(true);
    LAST_HEAD=h;
    drawPages($('cvh'), h, z, shadow, guides);
    if(EDITION==='both'){
      fetchRender(CUR.head, false, false, 'small')
        .then(o=>{ if(seq===RSEQ) drawPages($('cvh2'), o, z, shadow, guides); }).catch(()=>{});
    }
    $('wdiff').innerHTML=wordDiff(CUR.head, text);
  } else show(false);
}
// how far the runner-up fell behind: a tie says so, a hair says how small
function marginText(m){
  m = +m;
  if(m === 0) return 'the runner-up <b>tied</b> it';
  if(m < 0.01) return 'the runner-up lost by <b>under 0.01</b> points';
  return `the runner-up lost by <b>${m.toFixed(2)}</b> points`;
}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;')}

// ---- state ----
let ROWS = [], FAM = 'ALL', MANF = 'all', SHOWN = [], PAINTED = 0;
let CUR = null;                     // the row detail the box is showing
let CHANGED = new Set();            // rel\0pos of rows that differ from git HEAD
let CLOSEM = new Map();             // rel\0pos -> how close its runner-up came
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
// per-row facts the filter reads on every keystroke, computed once per row
// (and again only when the row's text changes: a save resets them)
const words = r => (r._w !== undefined && r._wt === r[3]) ? r._w : (r._wt = r[3], r._w = wordsIn(r[3]));
// a sentence matches wherever its line breaks fall: the line, box and wait
// codes read as the word gap they stand for (the raw text, codes and all,
// is searched too)
const flat = t => t.replace(/<FF0[1234]>|<FFF[5-7]>|<FFFB>|<FFEF>/g, ' ')
                   .replace(/<FF05><[0-9A-F]{2}><[0-9A-F]{2}>/g, '').replace(/\s+/g, ' ');
// curly quotes search as their straight forms, either way round
const plainQuotes = t => t.replace(/[\u2018\u2019\u201B\u2032]/g, "'").replace(/[\u201C\u201D\u201F\u2033]/g, '"');
const hay = r => (r._h !== undefined && r._ht === r[3] + r[5]) ? r._h
  : (r._ht = r[3] + r[5],
     r._h = plainQuotes(flat(r[3]) + '\u0000' + r[3] + ' ' + r[5] + ' ' + r[0] + ' ' + r[1] + ' ' + r[2]).toLowerCase());
// RANDOM ORDER: the shuffle button gives every row a random key and the list
// sorts by it until the button is pressed again (a second press reshuffles,
// a long press - or shift-click - goes back to table order)
let SHUF = null;
// repeat folding (see collapseRepeats): on unless the viewer was told off
let DUPT = true;
try{ DUPT = localStorage.getItem('textvis.dupes') !== '0'; }catch(e){}
function shuffled(list){
  if(!SHUF) return list;
  const key = r => { const k = r[0] + '\u0000' + r[2]; if(!SHUF.has(k)) SHUF.set(k, Math.random()); return SHUF.get(k); };
  return list.slice().sort((a, b) => key(a) - key(b));
}
function matches(q){
  return collapseRepeats(shuffled(filterRows(q)));
}
// REPEATED WORDING IS ONE ENTRY: the same text ships scene after scene (the
// Agastya Tree's three lines stand in every save room), so a list that paints
// every copy is mostly copies. Identical wording folds onto its first row,
// whose badge opens the rest in place; the key carries the state and the note
// so a manual row is never hidden behind an untouched one.
let FOLDED = 0;
function repeatKey(r){ return r[3] + '\u0000' + r[4] + '\u0000' + r[5]; }
function collapseRepeats(list){
  if(!DUPT){
    for(const r of list){ r._copies = null; r._foldedBy = null; }
    FOLDED = 0;
    return list;
  }
  const seen = new Map(), out = [];
  for(const r of list){
    const lead = seen.get(repeatKey(r));
    if(lead){
      r._copies = null;
      r._foldedBy = lead;
      (lead._copies || (lead._copies = [])).push(r);
      continue;
    }
    r._copies = null;
    r._foldedBy = null;
    seen.set(repeatKey(r), r);
    out.push(r);
  }
  FOLDED = list.length - out.length;
  return out;
}
function filterRows(q){
  const longonly = $('longonly').checked;
  const needle = plainQuotes(q).toLowerCase().replace(/\s+/g, ' ');
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
      if(MANF === 'changed' && !CHANGED.has(rel + '\u0000' + pos)) return false;
      if(MANF === 'close' && !CLOSEM.has(rel + '\u0000' + pos)) return false;
    } else if(longonly && (state === 'manual' || state === 'generated') && words(r) < 3){
      // the 3+ word filter is about English textboxes; a row with no English
      // yet (its draft is the Japanese) is never hidden by it.
      return false;
    }
    if(!needle) return true;
    return hay(r).includes(needle);
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
  const copies = rec._copies || [];
  return `<div class="k"><span class="fam">${esc(rel)}</span> #${esc(id)}${stateTag(state)}` +
         `${note ? '<span class="tag n">note</span>' : ''}<span class="pg"> · ${esc(pos)}</span>` +
         (copies.length ? `<span class="tag d" data-act="copies" title="this wording is in ${copies.length + 1} rows — open the other locations">×${copies.length + 1}</span>` : '') +
         `<button class="mini" data-act="find" title="open this row and search the PSP text for it">psp</button></div>` +
         `<div class="t">${esc(pretty(text)) || esc(note)}</div>` +
         (copies.length ? `<div class="copies">` + copies.map((c, i) =>
           `<div class="copy" data-i="${i}" title="open this copy"><span class="fam">${esc(c[0])}</span> #${esc(c[1])}` +
           `<span class="pg"> · ${esc(c[2])}</span></div>`).join('') + `</div>` : '');
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
                    (FOLDED ? ` · ${FOLDED} repeat${FOLDED === 1 ? '' : 's'} folded` : '') +
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
        const t = e.target;
        if(t.closest && t.closest('[data-act="copies"]')){ d.classList.toggle('open'); return; }
        const copy = t.closest && t.closest('.copy');
        if(copy && rec._copies){ const c = rec._copies[+copy.dataset.i]; if(c) pick(c); return; }
        const hit = t.closest && t.closest('[data-act="find"]');
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
  return !(DIRTY || ERRDIRTY) || confirm('Discard unsaved edits to this row?');
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
// ---- the row's PSP errata: edited here, previewed as you type, saved to
// translation/psp_errata.tsv (the port applies them at the row's one write) ----
let ERR = [], ERRDIRTY = false, ERRT = null, ERRSEQ = 0;
function fillErrata(d){
  const e = d.errata;
  $('errata').hidden = !e;
  $('errmeta').textContent = e ? `${e.rel} · ${e.pos}` : '(this row names no single PSP-US line)';
  ERR = e ? e.rows.map(r => ({find: r.find, replace: r.replace, note: r.note || ''})) : [];
  ERRDIRTY = false;
  drawErrRows();
  errPreview();
}
function drawErrRows(){
  const box = $('errrows'); box.innerHTML = '';
  ERR.forEach((r, i) => {
    const row = document.createElement('div'); row.className = 'errrow';
    for(const k of ['find', 'replace', 'note']){
      const inp = document.createElement('input');
      inp.value = r[k]; inp.placeholder = k; inp.spellcheck = false; inp.dataset.i = i;
      inp.oninput = () => { r[k] = inp.value; errChanged(); };
      row.appendChild(inp);
    }
    const del = document.createElement('button');
    del.className = 'btn'; del.textContent = '✕'; del.title = 'remove this errata';
    del.onclick = () => { ERR.splice(i, 1); drawErrRows(); errChanged(); };
    row.appendChild(del);
    box.appendChild(row);
  });
}
function errChanged(){
  ERRDIRTY = true;
  $('errata').classList.add('dirty');
  $('errsave').disabled = false;
  errPreview();
}
function errPreview(){
  clearTimeout(ERRT);
  $('errata').classList.toggle('dirty', ERRDIRTY);
  $('errsave').disabled = !ERRDIRTY;
  if(!CUR || !CUR.errata) return;
  if(!ERRDIRTY){
    $('errline').textContent = CUR.errata.rows.length ? '' : CUR.errata.raw;
    $('errstat').textContent = CUR.errata.rows.length ? '' : 'no errata on this line';
    $('errprevk').hidden = true; $('cve').hidden = true;
    if(CUR.errata.rows.length) errFetch();
    return;
  }
  ERRT = setTimeout(errFetch, 150);
}
async function errFetch(){
  const seq = ++ERRSEQ;
  const z = Math.max(1, Math.round(+$('zoom').value));
  try{
    const r = await fetch('/errata/preview', {method:'POST', headers:{'Content-Type':'application/json'},
                                              body: JSON.stringify({rel: CUR.rel, pos: CUR.pos, rows: ERR})});
    const d = await r.json();
    if(seq !== ERRSEQ) return;
    if(!r.ok) throw new Error(d.error || 'preview failed');
    $('errline').textContent = d.applied;
    const notes = [];
    if(d.manual) notes.push('a manual row ships instead: errata change only the generated row');
    if(d.missed.length) notes.push(`not placed in the row's English (the port will): ${d.missed.join(' · ')}`);
    $('errstat').innerHTML = notes.length ? `<span class="warn">${esc(notes.join(' · '))}</span>`
                                          : (ERRDIRTY ? 'unsaved' : '');
    const show = ERRDIRTY;
    $('errprevk').hidden = !show; $('cve').hidden = !show;
    if(show){
      const pr = await fetchRender(d.en, false, false);
      if(seq !== ERRSEQ) return;
      drawPages($('cve'), pr, z, $('shadow').checked, $('guides').checked);
    }
  }catch(e){
    if(seq !== ERRSEQ) return;
    $('errstat').innerHTML = `<span class="warn">${esc(e.message || e)}</span>`;
  }
}
async function saveErrata(){
  if(!CUR || !CUR.errata) return;
  try{
    const r = await fetch('/errata', {method:'POST', headers:{'Content-Type':'application/json'},
                                      body: JSON.stringify({rel: CUR.rel, pos: CUR.pos, rows: ERR})});
    const d = await r.json();
    if(!r.ok) throw new Error(d.error || 'save failed');
    CUR.errata = d.errata;
    ERRDIRTY = false;
    $('errata').classList.remove('dirty');
    $('errsave').disabled = true;
    $('errstat').textContent = 'saved to translation/psp_errata.tsv — the next port writes the row';
  }catch(e){ $('errstat').innerHTML = `<span class="warn">${esc(e.message || e)}</span>`; }
}
$('erradd').onclick = () => { ERR.push({find: '', replace: '', note: ''}); drawErrRows(); ERRDIRTY = true; errPreview();
  const ins = $('errrows').querySelectorAll('input'); if(ins.length) ins[ins.length - 3].focus(); };
$('errsave').onclick = saveErrata;
$('shuffle').onclick = e => {
  SHUF = e.shiftKey && SHUF ? null : new Map();
  $('shuffle').classList.toggle('on', !!SHUF);
  $('shuffle').textContent = SHUF ? 'reshuffle' : 'shuffle';
  if(MODE === 'rows'){ SHOWN = matches($('filt').value.trim()); renderList(); }
  setStatus(SHUF ? 'random order (shift-click: table order)' : 'table order');
};
$('reload').onclick = async () => {
  if(!confirmDiscard()) return;
  setStatus('reloading…');
  try{
    const r = await fetch('/reload', {method:'POST'});
    const d = await r.json();
    if(!r.ok) throw new Error(d.error || 'reload failed');
    await loadFont();
    await loadRows();
    if(CUR){ DIRTY = false; ERRDIRTY = false; await pick([CUR.rel, '', CUR.pos]); }
    setStatus(`reloaded: ${d.rows} rows, ${d.modules} modules`);
  }catch(e){ setStatus(String(e.message || e), true); }
};

function setDetail(d){
  CUR = d;
  const id = (d.gen && d.gen.id) || (d.man && d.man.id) || '';
  $('locid').textContent = `${d.rel}  #${id}  ·  pos ${d.pos}`;
  $('badge').innerHTML = stateTag(d.state);
  fillSources(d);
  fillErrata(d);
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
  // a folded row's wording just changed, so its group is not one text
  // anymore: re-fold the list and keep the scroll where the reader had it
  if(rec._copies || rec._foldedBy){
    const top = $('list').scrollTop;
    SHOWN = matches($('filt').value.trim());
    renderList();
    // paint on until the row the reader had is within reach again
    while(PAINTED < SHOWN.length && $('list').scrollTop < top - 1){
      appendRows();
      $('list').scrollTop = top;
    }
    return;
  }
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
    SEARCH_T = setTimeout(() => { SHOWN = matches(q); renderList(); }, 120);
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
  $('dupeslab').style.display = m === 'rows' ? '' : 'none';
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
    const here = CUR && ROWS.find(r => r[0] === CUR.rel && r[2] === CUR.pos);
    const cur = here ? SHOWN.findIndex(r => r === here || r === here._foldedBy) : -1;
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
  // Up/Down step rows; Left/Right stay the text box's own cursor keys
  const step = {'ArrowDown': 1, 'ArrowUp': -1}[e.key];
  if(!step) return;
  e.preventDefault();
  stepRow(step);
};
$('fam').onchange = e => { FAM = e.target.value; if(MODE === 'rows'){ SHOWN = matches($('filt').value.trim()); renderList(); } };
$('manfilt').onchange = async e => {
  MANF = e.target.value;
  if(MANF === 'changed'){
    // asked anew each time: the working tree moves under the viewer
    try{
      const r = await fetch('/changed?ref=HEAD');
      const d = await r.json();
      if(!r.ok) throw new Error(d.error || 'git failed');
      CHANGED = new Set(d.map(([rel, pos]) => rel + '\u0000' + pos));
    }catch(err){ setStatus(String(err.message || err), true); }
  }
  if(MANF === 'close'){
    try{
      const r = await fetch('/close');
      const d = await r.json();
      CLOSEM = new Map(d.rows.map(([rel, pos, m]) => [rel + '\u0000' + pos, m]));
      if(d.missing) setStatus('no build/close_calls.tsv yet: the port writes it (or run close_calls.py)', true);
    }catch(err){ setStatus(String(err.message || err), true); }
  }
  if(MODE === 'rows'){
    SHOWN = matches($('filt').value.trim());
    // the closest calls first
    if(MANF === 'close' && !SHUF) SHOWN.sort((a, b) => CLOSEM.get(a[0] + '\u0000' + a[2]) - CLOSEM.get(b[0] + '\u0000' + b[2]));
    renderList();
  }
};
$('edition').value = EDITION;
$('edition').onchange = e => {
  EDITION = e.target.value;
  try{ localStorage.setItem('textvis.edition', EDITION); }catch(err){}
  loadFont();                       // the primary edition's glyphs, then a redraw
  if(MODE === 'rows') renderList();
};
$('longonly').onchange = () => { if(MODE === 'rows'){ SHOWN = matches($('filt').value.trim()); renderList(); } };
$('dupes').checked = DUPT;
$('dupes').onchange = () => {
  DUPT = $('dupes').checked;
  try{ localStorage.setItem('textvis.dupes', DUPT ? '1' : '0'); }catch(e){}
  if(MODE === 'rows'){ SHOWN = matches($('filt').value.trim()); renderList(); }
};
for(const b of document.querySelectorAll('.mode')) b.onclick = () => setMode(b.dataset.mode);
$('save').onclick = saveDraft;
$('copylines').onclick = () => { if(LAST_NOW) copyText(`${rowHead()}\n${linesText(LAST_NOW)}`); };
$('copydiff').onclick = () => {
  if(!LAST_NOW) return;
  copyText(LAST_HEAD
    ? `${rowHead()}\nHEAD:\n${linesText(LAST_HEAD)}\nNOW:\n${linesText(LAST_NOW)}`
    : `${rowHead()}\n(same as HEAD)\n${linesText(LAST_NOW)}`);
};
$('find').onclick = findMatches;
// the selected words read as one thing ("all-you-can-eat dinner"): added
// to translation/phrases.tsv, then the box and the flow's picture redrawn
$('phrase').onclick = async () => {
  const src = $('src'), sel = src.value.slice(src.selectionStart, src.selectionEnd);
  if(!sel.trim()){ $('stat').innerHTML = '<span class="warn">select the words to keep together first</span>'; return; }
  try{
    const r = await fetch('/phrases', {method:'POST', headers:{'Content-Type':'application/json'},
                                       body:JSON.stringify({phrase: sel, note: CUR ? `${CUR.rel} ${CUR.pos}` : ''})});
    const d = await r.json();
    if(!r.ok) throw new Error(d.error || 'not added');
    render();
    const b = $('phrase'); b.textContent = 'kept: ' + d.phrase;
    setTimeout(() => { b.textContent = 'keep together'; }, 2000);
  }catch(e){ $('stat').innerHTML = `<span class="warn">${esc(e.message || e)}</span>`; }
};
$('copy').onclick = () => { if(CUR) copyText(`${CUR.rel} ${CUR.pos}`); };
$('copyt').onclick = () => { if(CUR) copyText(CUR.initial); };
const srcEl = $('src');
srcEl.oninput = () => { DIRTY = true; updateDirty(); render(); };
// a picked row is one TSV line: a break is a code, not a newline, so Enter
// types the row's own line code - <FFF6> for the battle box (BTLP, the TALK
// negotiation lines), <FF03> for every other box (typed no-row text keeps
// Enter: that is the flow-layout demo)
function lineCode(){
  const t = srcEl.value;
  if(/<FFF6>/.test(t)) return '<FFF6>';
  if(/<FF03>/.test(t)) return '<FF03>';
  return /^(BTLP|TALK)/.test(CUR.rel) ? '<FFF6>' : '<FF03>';
}
srcEl.onkeydown = e => {
  // A CODE IS ONE CHARACTER TO ERASE: Backspace right after a '<...>' token
  // (Delete right before one) takes the whole token, never half a code.
  if((e.key === 'Backspace' || e.key === 'Delete') && srcEl.selectionStart === srcEl.selectionEnd){
    const t = srcEl.value, at = srcEl.selectionStart;
    const m = e.key === 'Backspace' ? /<[^<>]*>$/.exec(t.slice(0, at))
                                    : /^<[^<>]*>/.exec(t.slice(at));
    if(m){
      e.preventDefault();
      const a = e.key === 'Backspace' ? at - m[0].length : at;
      srcEl.setRangeText('', a, a + m[0].length, 'end');
      DIRTY = true; updateDirty(); render();
      return;
    }
  }
  if(CUR && e.key === 'Enter' && !e.ctrlKey && !e.metaKey){
    e.preventDefault();
    const code = lineCode(), a = srcEl.selectionStart, b = srcEl.selectionEnd;
    srcEl.setRangeText(code, a, b, 'end');
    DIRTY = true; updateDirty(); render();
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
window.addEventListener('beforeunload', e => { if(DIRTY || ERRDIRTY){ e.preventDefault(); e.returnValue = ''; } });
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
