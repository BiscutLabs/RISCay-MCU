/* SPDX-License-Identifier: Apache-2.0
 * Generic SPI NOR boot. All image policy is the ordinary loader ABI. */
typedef unsigned int u32;
#define REG(n) (*(volatile u32 *)(0x30000000u+(n)))
#define CLOCK (1u<<3)
#define MOSI  (1u<<4)
#define CS    (1u<<5)
#define MISO  (1u<<6)
#define PINS  (CLOCK|MOSI|CS)
#define BOOT_SESSION (1u<<3)
#define LOADER_HOLD (1u<<5)
#define PERSIST_PENDING (1u<<6)
#define IMAGE_MAGIC 0x59435352u
#define SLOTS_MAGIC 0x32425352u
typedef struct { u32 stride, a, b, golden; } slots;
extern const u32 riscay_program_capacity;

static void kick(void) { REG(32)=0x57444f47u; }
static void select_flash(int selected) {
    REG(24)=(REG(24)&~PINS)|(selected ? 0 : CS);
}
static u32 transfer(u32 out) {
    u32 in=0, pins=REG(24)&~(CLOCK|MOSI);
    for(u32 bit=0;bit<8;bit++) {
        u32 low=pins|((out&0x80u) ? MOSI : 0);
        REG(24)=low;
        REG(24)=low|CLOCK;
        in=(in<<1)|((REG(20)&MISO)!=0);
        REG(24)=low;
        out<<=1;
    }
    return in;
}
static u32 word(void) {
    u32 v=0;
    for(u32 b=0;b<32;b+=8) v|=transfer(0xffu)<<b;
    return v;
}
static int idle_flash(void) {
    /* A stuck or busy device cannot turn boot into an unbounded kick loop. */
    for(u32 attempt=0;attempt<256;attempt++) {
        select_flash(1); transfer(5); u32 status=transfer(0xffu); select_flash(0);
        if(!(status&1u)) return 1;
    }
    return 0;
}
static void address_command(u32 command,u32 address) {
    select_flash(1); transfer(command);
    transfer(address>>16); transfer(address>>8); transfer(address);
}
static void write_enable(void) { select_flash(1); transfer(6); select_flash(0); }
static int write_idle(void) {
    /* Time and iteration bounds both apply. Kicks permit a bounded slow erase,
       never an indefinitely busy peripheral. Timing metadata is an oscillator
       bound, not a promise that every external flash part meets this timeout. */
    u32 began=REG(4);
    for(u32 poll=0;poll<65536;poll++) {
        select_flash(1); transfer(5); u32 status=transfer(0xffu); select_flash(0);
        if(!(status&1u)) return 1;
        if(REG(4)-began>2000u) return 0;
        if(!(poll&255u)) kick();
    }
    return 0;
}
static u32 crc_word(u32 crc,u32 value) {
    for(u32 b=0;b<32;b++) {
        u32 low=(crc^value)&1u;
        crc=(crc>>1)^(low ? 0xedb88320u : 0); value>>=1;
    }
    return crc;
}
/* Directory is factory-owned. Field persistence never erases it or golden.
   Bounds precede every addition/multiplication that could wrap a flash address. */
static int directory(u32 *h,slots *s) {
    u32 crc=~0u;
    for(u32 n=0;n<7;n++) crc=crc_word(crc,h[n]);
    if(h[0]!=SLOTS_MAGIC || h[1]!=2 || ~crc!=h[7] || !h[2] ||
       (h[2]&4095u) || h[2]>0x555000u || (h[3]&4095u) ||
       h[3]>0x1000000u || 4096u+3*h[2]>h[3] ||
       h[4]!=4096u+h[2] || h[5]!=4096u+2*h[2] || h[6]!=4096u) return 0;
    s->stride=h[2];s->a=h[4];s->b=h[5];s->golden=h[6];return 1;
}
static int record_header(u32 base,u32 capacity,u32 *generation,int body_check) {
    u32 h[12],crc=~0u;
    address_command(3,base);
    for(u32 n=0;n<12;n++) { h[n]=word(); if(n<11) crc=crc_word(crc,h[n]); kick(); }
    int ok=h[0]==IMAGE_MAGIC && h[1]==2 && h[11]==~crc && capacity>=48 &&
        h[2] && !(h[2]&3u) && h[2]<=capacity-48 && h[2]<=riscay_program_capacity &&
        !(h[3]&3u) && h[3]<h[2] && h[5]==0x10000u &&
        h[6]<=REG(112) && !(h[7]&~REG(116)) && h[8]<=REG(120);
    if(ok && body_check) {
        crc=~0u;
        for(u32 offset=0;offset<h[2];offset+=4) {crc=crc_word(crc,word());kick();}
        ok=~crc==h[4];
    }
    select_flash(0);*generation=h[10];return ok;
}
static u32 image_header_word(u32 n,u32 generation,int extended) {
    if(n==0) return IMAGE_MAGIC;
    if(n==1) return extended ? 2 : 1;
    if(n<10) return REG(88+4*n);
    return generation;
}
static u32 image_word(u32 offset,u32 generation,int extended) {
    u32 header=extended ? 48 : 40;
    if(offset<40 || (extended && offset==40)) return image_header_word(offset>>2,generation,extended);
    if(extended && offset==44) {
        u32 crc=~0u;
        for(u32 n=0;n<11;n++) crc=crc_word(crc,image_header_word(n,generation,1));
        return ~crc;
    }
    return *(volatile const u32 *)(0x10000000u+offset-header);
}
static int persist_at(u32 base,u32 capacity,u32 generation,int extended) {
    u32 header=extended ? 48 : 40;
    if(capacity<header || REG(96)>capacity-header) return 0;
    u32 total=REG(96)+header;
    /* In A/B mode this is the inactive field slot. The other field image and
       external golden stay byte-for-byte intact throughout erase/program. */
    for(u32 sector=0;sector<total;sector+=4096) {
        write_enable(); address_command(0x20,base+sector); select_flash(0);
        if(!write_idle()) return 0;
        kick();
    }
    /* Program complete aligned words, respecting each 256-byte page boundary.
       The magic/commit word at address zero remains erased until read-back. */
    for(u32 page=0;page<total;page+=256) {
        u32 start=page ? page : 4;
        u32 end=page+256; if(end>total) end=total;
        write_enable(); address_command(2,base+start);
        for(u32 offset=start;offset<end;offset+=4) {
            u32 value=image_word(offset,generation,extended);
            for(u32 b=0;b<4;b++) { transfer(value); value>>=8; }
        }
        select_flash(0); if(!write_idle()) return 0;
        kick();
    }
    address_command(3,base+4);
    for(u32 offset=4;offset<total;offset+=4) {
        if(word()!=image_word(offset,generation,extended)) { select_flash(0); return 0; }
        kick();
    }
    select_flash(0);
    write_enable(); address_command(2,base);
    u32 magic=IMAGE_MAGIC;
    for(u32 b=0;b<4;b++) { transfer(magic); magic>>=8; }
    select_flash(0); if(!write_idle()) return 0;
    address_command(3,base); u32 actual=word(); select_flash(0);
    return actual==IMAGE_MAGIC;
}
static int persist_image(void) {
    if(!idle_flash()) return 0;
    u32 h[8];slots s;
    address_command(3,0);
    for(u32 n=0;n<8;n++) {h[n]=word();kick();}
    select_flash(0);
    if(h[0]!=SLOTS_MAGIC) {
        /* Legacy/blank devices retain the single-slot ABI. Unknown metadata
           cannot authorize erasing a possibly damaged factory directory. */
        int blank=1,partial=(h[0]&IMAGE_MAGIC)==IMAGE_MAGIC && (h[1]&255u)==1;
        for(u32 n=0;n<8;n++) {
            if(h[n]!=~0u) blank=0;
            if(n && (h[n]&image_header_word(n,0,0))!=image_header_word(n,0,0)) partial=0;
        }
        if(!blank && !partial && !(h[0]==IMAGE_MAGIC && h[1]==1)) return 0;
        return persist_at(0,0x1000000u,0,0);
    }
    if(!directory(h,&s)) return 0;
    u32 ga,gb,latest=0,base=s.a;
    int a=record_header(s.a,s.stride,&ga,1),b=record_header(s.b,s.stride,&gb,1);
    if(a && (!b || ga>=gb)) {latest=ga;base=s.b;}
    else if(b) {latest=gb;base=s.a;}
    /* No generation wrap: refusing an update preserves a usable old image. */
    if(latest==~0u) return 0;
    return persist_at(base,s.stride,latest+1,1);
}
static void claim_bus(void) {
    REG(88)=1;
    u32 attempt;
    for(attempt=0;attempt<4096 && !(REG(88)&1u);attempt++) {}
    if(attempt==4096) for(;;) {} /* Independent watchdog retries a stuck boundary. */
    select_flash(0);
    REG(28)=(REG(28)|PINS)&~MISO;
}
static void release_bus(void) { select_flash(0); REG(88)=0; }
/* Header magic/version have been consumed; the READ stream is at word two. */
static int load_stream(int extended) {
    REG(80)=1; /* BEGIN_OPEN: explicitly invalidate before replacing metadata. */
    if(!(REG(76)&BOOT_SESSION)) { select_flash(0); return 0; }
    for(u32 h=0;h<8;h++) {
        REG(84)=word();
        /* LAST_ERROR is shared host diagnostics, not this owner's result.
           A rejected concurrent host command must not abort a valid boot. */
        u32 status=REG(76);
        if(!(status&BOOT_SESSION) || ((status>>16)&15u)!=h+1) {
            select_flash(0); REG(80)=4; return 0;
        }
    }
    if(extended) {word();word();} /* Generation and header CRC, already checked. */
    u32 length=REG(96);
    for(u32 offset=0;offset<length;offset+=4) {
        REG(84)=word();
        if(!(REG(76)&BOOT_SESSION)) { select_flash(0); REG(80)=4; return 0; }
        kick();
    }
    select_flash(0); REG(80)=2; /* VERIFY after the last SRAM/CRC completion. */
    if((REG(76)&(1u|BOOT_SESSION))!=1u) { REG(80)=4; return 0; }
    return 1;
}
static int load_slot(u32 base,u32 capacity) {
    u32 generation;
    if(!record_header(base,capacity,&generation,0)) return 0;
    address_command(3,base+8);
    return load_stream(1);
}
static int load_flash(void) {
    if(!idle_flash()) return 0;
    address_command(3,0);
    u32 h[8];h[0]=word();h[1]=word();
    if(h[0]==IMAGE_MAGIC && h[1]==1) return load_stream(0);
    if(h[0]!=SLOTS_MAGIC || h[1]!=2) {select_flash(0);return 0;}
    for(u32 n=2;n<8;n++) {h[n]=word();kick();}
    select_flash(0);
    slots s;if(!directory(h,&s)) return 0;
    u32 ga,gb;
    int a=record_header(s.a,s.stride,&ga,0),b=record_header(s.b,s.stride,&gb,0);
    if(a && (!b || ga>=gb)) {
        if(load_slot(s.a,s.stride)) return 1;
        if(b && load_slot(s.b,s.stride)) return 1;
    } else {
        if(b && load_slot(s.b,s.stride)) return 1;
        if(a && load_slot(s.a,s.stride)) return 1;
    }
    return load_slot(s.golden,s.stride);
}
u32 boot_main(void) {
    kick();
    /* Wait for the entire ADC transaction, not merely its pin-level CS. */
    claim_bus();
    u32 status=REG(76);
    if(!(status&(1u|LOADER_HOLD))) load_flash();
    release_bus();
    status=REG(76);
    if((status&1u) && !(status&(LOADER_HOLD|PERSIST_PENDING))) REG(80)=3;
    for(;;) {
        /* A blocking status read wakes for START or an explicit persistence
           request. Ordinary verified uploads never erase external storage. */
        status=REG(80);
        if(status&4u) break;
        if(status&PERSIST_PENDING) {
            claim_bus(); int ok=persist_image(); release_bus();
            REG(80)=ok ? 6 : 7;
        }
    }
    /* This intentional idle-loader read is the only unstarted watchdog lease. */
    return REG(0); /* Assembly tail handoff; no ROM frame remains on the stack. */
}
