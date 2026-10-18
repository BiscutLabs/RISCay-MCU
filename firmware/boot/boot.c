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
static u32 image_word(u32 offset) {
    if(offset==0) return 0x59435352u;
    if(offset==4) return 1u;
    if(offset<40) return REG(88+offset);
    return *(volatile const u32 *)(0x10000000u+offset-40);
}
static int persist_image(void) {
    if(!idle_flash()) return 0;
    u32 total=REG(96)+40u;
    /* Single slot: erase the old commit record before changing its body.
       Any interrupted update may fall back to I2C; no rollback is promised. */
    for(u32 sector=0;sector<total;sector+=4096) {
        write_enable(); address_command(0x20,sector); select_flash(0);
        if(!write_idle()) return 0;
        kick();
    }
    /* Program complete aligned words, respecting each 256-byte page boundary.
       The magic/commit word at address zero remains erased until read-back. */
    for(u32 page=0;page<total;page+=256) {
        u32 start=page ? page : 4;
        u32 end=page+256; if(end>total) end=total;
        write_enable(); address_command(2,start);
        for(u32 offset=start;offset<end;offset+=4) {
            u32 value=image_word(offset);
            for(u32 b=0;b<4;b++) { transfer(value); value>>=8; }
        }
        select_flash(0); if(!write_idle()) return 0;
        kick();
    }
    address_command(3,4);
    for(u32 offset=4;offset<total;offset+=4) {
        if(word()!=image_word(offset)) { select_flash(0); return 0; }
        kick();
    }
    select_flash(0);
    write_enable(); address_command(2,0);
    u32 magic=image_word(0);
    for(u32 b=0;b<4;b++) { transfer(magic); magic>>=8; }
    select_flash(0); if(!write_idle()) return 0;
    address_command(3,0); u32 actual=word(); select_flash(0);
    return actual==image_word(0);
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
static int load_flash(void) {
    if(!idle_flash()) return 0;
    select_flash(1); transfer(3); transfer(0); transfer(0); transfer(0);
    if(word()!=0x59435352u || word()!=1u) { select_flash(0); return 0; }
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
