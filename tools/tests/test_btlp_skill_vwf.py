import unittest
"""Execute installed battle SPRT/FT4 paths, semantic ownership and row-latched metrics."""
from pathlib import Path
import struct,sys
ROOT=Path(__file__).resolve().parents[2];HERE=ROOT/'scratch/battle_objvwf_audit'
sys.path.insert(0,str(ROOT/'tools/tests'))

def item_fixture():
    sys.path.insert(0,str(ROOT/'src/injection_tools'))
    import btlfont,toolbelt
    symbols={m.group(2):int(m.group(1),16) for line in (ROOT/'build/persona.sym').read_text().splitlines()
             if (m:=re.fullmatch(r'([0-9A-Fa-f]{8}) (\S+)',line))}
    ident,codes=next(iter(btlfont.item_vwf_records().items()))
    return (toolbelt.asm_equ('BTLP_ITEM_FULL_ADDR'),toolbelt.asm_equ('BTLP_ITEM_IDS_ADDR'),
            symbols['btl_item_owner'],ident,codes)

def test_flat(self, item=False):
    from mips_cpu import CPU,REG
    sys.path.insert(0,str(ROOT/'src/injection_tools'))
    import toolbelt
    SKILL_BIT=toolbelt.asm_equ('SKILL_BIT_OFFSET')     # skill slot 0's ownership bit
    BASE=0x800643c4
    btl=(ROOT/'build/BTLP.BIN').read_bytes(); retail=(ROOT/'data/psx/BTLP.BIN').read_bytes(); width=(ROOT/'build/sf_width.bin').read_bytes()
    OBJ=0x80100000;LIST=0x80101000;DESC=0x80102000;PRIM=0x80120000;POOL=0x80140000;DMODE=0x80118000;SRC=0x8002c248
    
    fixture=item_fixture() if item else None
    if fixture:SRC=fixture[0]
    glyphs=fixture[4] if fixture else bytes([0xa6,0xae,0xb8])
    def j(addr):return 0x08000000|((addr>>2)&0x3ffffff)
    def run(enabled,hook,flip=False):
     c=CPU();c.load(0x80010000,(ROOT/"build/SLPS_005.00").read_bytes()[0x800:]);c.load(BASE,btl)
     if not hook:
       for a in (0x80088e80,0x800891a4,0x80088f84,0x80088f88,0x80088fa8,0x80088fac,0x80088fdc): c.load(a,retail[a-BASE:a-BASE+4])
     c.write(OBJ+0x68,LIST);c.write(LIST,1);c.write(LIST+4,DESC);c.write(DESC,12,2);c.write(DESC+2,24,2);c.write(DESC+4,SRC)
     c.write(DESC+8,len(glyphs),1);c.write(DESC+9,0x20,1);c.write(DESC+10,12,1);c.write(DESC+11,0,1)
     c.load(SRC,glyphs);c.write(0x800120a0,(1<<SKILL_BIT) if enabled else 0,2)
     if fixture:c.write(fixture[1],fixture[3],2);c.write(fixture[2],1 if enabled else 0,1)
     c.write(0x800cf0f8,0,1);c.write(0x800cf098,POOL);c.write(0x800eec34,PRIM);c.write(0x800eec4c,DMODE)
     c.write(0x800f0c78,50,2);c.write(0x800f0c7c,40,2)
     c.r[REG['a0']]=OBJ;c.r[REG['sp']]=0x801ff000;c.r[REG['ra']]=0x8000fff0;c.start(0x80088e80)
     changed=False
     for _ in range(5000):
      if c.pc==0x8000fff0:break
      if c.pc==0x8002c3e0:c.start(c.r[REG['ra']]);continue
      if flip and not changed and c.pc==0x800890fc:
       c.write(fixture[2],0 if enabled else 1,1) if fixture else c.write(0x800120a0,0 if enabled else 1,2)
       changed=True
      c.step()
     else:raise AssertionError('flat renderer did not return')
     return [bytes(c.read(PRIM+i*20+k,1) for k in range(20)) for i in range(len(glyphs))],c
    retail,_=run(False,False)
    fallback,_=run(False,True,True)
    assert retail==fallback,'fallback altered retail SPRT packets'
    prop,cpu=run(True,True,True)
    pen=0
    for i,(a,b,code) in enumerate(zip(retail,prop,glyphs)):
     expected=62+pen-(width[code]>>4);assert int.from_bytes(b[8:10],'little')==expected
     import btlfont
     cell=btlfont.art_mapping()[0].get(code,code)
     assert b[12:14]==bytes((cell%31*8,cell//31*12)), 'wrong proportional atlas cell'
     assert a[:8]+a[10:12]+a[14:]==b[:8]+b[10:12]+b[14:],'non-position/UV packet data changed'
     pen+=width[code]&15
    assert cpu.r[REG['sp']]==0x801ff000
    print('Actual flat renderer: VWF origins, fallback bytes, packet identity, row latch, stack restoration passed.')

"""Run the actual battle FT4 loop with a scratch row-latched VWF hook."""
from pathlib import Path
import re,sys
ROOT=Path(__file__).resolve().parents[2];HERE=ROOT/'build'
sys.path.insert(0,str(ROOT/'tools/tests'))

def test_rot(self, item=False):
    from mips_cpu import CPU,REG
    sys.path.insert(0,str(ROOT/'src/injection_tools'))
    import toolbelt
    SKILL_BIT=toolbelt.asm_equ('SKILL_BIT_OFFSET')     # skill slot 0's ownership bit
    btl=(ROOT/'build/BTLP.BIN').read_bytes();retail=(ROOT/'data/psx/BTLP.BIN').read_bytes();width=(ROOT/'build/sf_width.bin').read_bytes()
    sym={m.group(2):int(m.group(1),16) for l in (HERE/'persona.sym').read_text().splitlines() if (m:=re.match(r'^([0-9a-fA-F]{8})\s+(\S+)',l))}
    OBJ=0x80100000;LIST=0x80101000;DESC=0x80102000;PRIM=0x80120000;POOL=0x80140000;SRC=0x8002c248
    fixture=item_fixture() if item else None
    if fixture:SRC=fixture[0]
    glyphs=fixture[4] if fixture else bytes([0xa6,0xae,0xb8])
    j=lambda addr:0x08000000|((addr>>2)&0x3ffffff)
    def run(enabled,hook,flip=False):
     c=CPU();c.load(0x80010000,(ROOT/"build/SLPS_005.00").read_bytes()[0x800:]);c.load(0x800643c4,btl)
     if not hook:
       for a in (0x800891b0,0x800895c8,0x800892c8,0x800892cc,0x80089370,0x80089374):c.load(a,retail[a-0x800643c4:a-0x800643c4+4])
     c.write(OBJ+0x68,LIST);c.write(LIST,1);c.write(LIST+4,DESC);c.write(DESC,12,2);c.write(DESC+2,24,2);c.write(DESC+4,SRC)
     c.write(DESC+8,len(glyphs),1);c.write(DESC+9,0x20,1);c.write(DESC+10,12,1);c.write(DESC+11,0,1)
     c.load(SRC,glyphs);c.write(0x800120a0,(1<<SKILL_BIT) if enabled else 0,2)
     if fixture:c.write(fixture[1],fixture[3],2);c.write(fixture[2],1 if enabled else 0,1)
     c.write(0x800cf0f8,0,1);c.write(0x800cf098,POOL);c.write(0x800eec3c,PRIM)
     c.r[REG['a0']]=OBJ;c.r[REG['sp']]=0x801ff000;c.r[REG['ra']]=0x8000fff0;c.start(0x800891b0)
     stops={0x8002ad30,0x80029b9c,0x80029d1c,0x80029d4c,0x8002afc0,0x80029fbc}
     changed=False
     for _ in range(6000):
      if c.pc==0x8000fff0:break
      if c.pc in stops:c.start(c.r[REG['ra']]);continue
      if c.pc==0x80029e0c:
       for i,reg in enumerate(('a0','a1','a2','a3')):
        src=c.r[REG[reg]];dst=c.read(c.r[REG['sp']]+0x10+i*4)
        c.write(dst,c.read(src,2),2);c.write(dst+2,c.read(src+2,2),2)
       c.start(c.r[REG['ra']]);continue
      if flip and not changed and c.pc==0x8008936c:
       c.write(fixture[2],0 if enabled else 1,1) if fixture else c.write(0x800120a0,0 if enabled else 1,2)
       changed=True
      c.step()
     else:raise AssertionError(f'transformed renderer did not return: {c.pc:#x}')
     return [bytes(c.read(PRIM+i*40+k,1) for k in range(40)) for i in range(len(glyphs))],c
    retail,_=run(False,False)
    fallback,_=run(False,True,True)
    assert retail==fallback,'fallback altered retail FT4 packets'
    prop,cpu=run(True,True,True)
    pen=0
    for a,b,code in zip(retail,prop,glyphs):
     expected=(12+pen-(width[code]>>4))&0xffff
     for off,dx in ((8,0),(16,8),(24,0),(32,8)):
      assert int.from_bytes(b[off:off+2],'little')==(expected+dx)&0xffff,(off,b.hex())
     import btlfont
     cell=btlfont.art_mapping()[0].get(code,code)
     for off,dx,dy in ((12,0,0),(20,8,0),(28,0,12),(36,8,12)):
      assert b[off:off+2]==bytes((cell%31*8+dx,cell//31*12+dy)), 'wrong proportional atlas quad'
     for off in (8,9,16,17,24,25,32,33,12,13,20,21,28,29,36,37):
      a=a[:off]+b[off:off+1]+a[off+1:]
     assert a==b,'non-position FT4 fields changed'
     pen+=width[code]&15
    assert cpu.r[REG['sp']]==0x801ff000
    print('Actual transformed renderer: VWF quad origins, fallback bytes, non-position fields, row latch, stack restoration passed.')

"""Installed assembled battle bridge register and row-latch regression."""
from pathlib import Path
import re,sys
ROOT=Path(__file__).resolve().parents[2];HERE=ROOT/'build'
sys.path.insert(0,str(ROOT/'tools/tests'))

def test_row_latch_and_live_glyph(self):
    from mips_cpu import CPU,REG
    sym={m.group(2):int(m.group(1),16) for line in (HERE/'persona.sym').read_text().splitlines() if (m:=re.match(r'^([0-9a-fA-F]{8})\s+(\S+)',line))}
    # The battle bridge reads the split table: text cells proportional, every
    # other cell the retail 8 px metric.
    image=(HERE/'BTLP.BIN').read_bytes();widths=(HERE/'btl_sf_width.bin').read_bytes()
    DESC=0x800e0100;SP=0x801f0000
    sys.path.insert(0,str(ROOT/'src/injection_tools'))
    import toolbelt as _tb
    SRC=_tb.asm_equ('SKILL_MENU_BUF');STRIDE=_tb.asm_equ('SKILL_MENU_STRIDE')
    FLAGS=_tb.asm_equ('SKILL_VWF_SLOTS_ADDR');BIT0=_tb.asm_equ('SKILL_BIT_OFFSET')
    cases=0
    def draw(mode,enabled,codes,flip=None,mutation=None,slot=0):
     nonlocal cases
     cases+=1
     c=CPU();c.load(0x80010000,(ROOT/"build/SLPS_005.00").read_bytes()[0x800:]);c.load(0x800643c4,image);c.write(DESC+4,SRC+slot*STRIDE);c.load(SRC+slot*STRIDE,bytes(codes));c.write(FLAGS,(1<<(BIT0+slot)) if enabled else 0,2)
     for reg in range(1,32):c.r[reg]=0x23450000+reg*0x101
     c.r[REG['sp']]=SP;c.r[REG['ra']]=0x8000fff0
     pos=[];advance=0
     for i in range(len(codes)):
      if i==1 and flip is not None:c.write(FLAGS,flip,2)
      if i==1 and mutation is not None:c.write(SRC+slot*STRIDE+i,mutation,1)
      code=c.read(SRC+slot*STRIDE+i,1);c.r[REG['v0']]=100;c.r[REG['a1']]=200
      if mode=='flat':c.r[REG['t3']]=DESC;c.r[REG['t0']]=i;c.r[REG['a3']]=SRC+slot*STRIDE+i
      else:c.r[REG['s5']]=DESC;c.r[REG['s3']]=i;c.r[REG['s4']]=SRC+slot*STRIDE+i
      before=c.r.copy();c.start(sym['btl_sf_'+mode+'_entry']);stop=0x80088f8c if mode=='flat' else 0x800892d0
      for _ in range(300):
       if c.pc==stop:break
       c.step()
      else:raise AssertionError('no return')
      origin=c.r[REG['v0' if mode=='flat' else 'a1']]-(100 if mode=='flat' else 200)
      if origin>=2**31:origin-=2**32
      want=(advance-(widths[code]>>4)) if enabled else i*8
      assert origin==want,(mode,enabled,i,origin,want)
      if enabled:advance+=widths[code]&15
      allowed={REG['v1'],REG['v0' if mode=='flat' else 'a1']}
      for r in range(1,32):
       if r not in allowed:assert c.r[r]==before[r],(mode,enabled,i,r,hex(c.r[r]),hex(before[r]))
      pos.append(origin)
     return pos
    for mode in ('flat','rot'):
     for slot in range(7):
      for enable in (False,True):
       for code in range(256):
        if code==255:continue
        draw(mode,enable,[0xa6,code,0xb8],flip=0 if enable else 255,slot=slot)
       draw(mode,enable,[0xa6,0xad,0xb8],flip=0 if enable else 255,mutation=0,slot=slot)
    print(f'{cases:,} rows including mutation cases pass for both renderers; row eligibility is latched, pen uses current glyph metrics.')
    print('Both production battle paths preserve a latched row decision and the current glyph metrics.')

class BattleSkillVwf(unittest.TestCase):
    test_flat = test_flat
    test_rot = test_rot
    def test_item_flat(self):test_flat(self,item=True)
    def test_item_rot(self):test_rot(self,item=True)
    test_row_latch_and_live_glyph = test_row_latch_and_live_glyph
