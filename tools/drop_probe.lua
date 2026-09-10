-- Test-only real input fixture: 0G must still permit soft and sonic drop.
local json=require('json')
local prefix=assert(os.getenv('TGM_TEST_PLUGIN'))
local function load(name)
    local f=assert(io.open(prefix..'/'..name)); local data=json.parse(f:read('a')); f:close(); return data
end
local s=manager.machine.devices[':maincpu'].spaces.program
local native=dofile(prefix..'/native.lua').new(s,load('native.json'),load('catalog.json'))
native:sync({players={{gravity=0,lock=90},{gravity=0}},global={}})
dofile(assert(os.getenv('TGM_TEST_GAMEPLAY')))
local fields={}
for _,port in pairs(manager.machine.ioport.ports) do
    for name,field in pairs(port.fields) do fields[name]=field end
end
local function press(name,down) assert(fields[name],name):set_value(down and 1 or 0) end
local frame=0
local start_y,soft_y,piece,writes
_G.drop_probe=emu.add_machine_frame_notifier(function()
    frame=frame+1
    native:install()
    assert(not native.error,native.error)
    local p=native:state(0)
    if frame==3000 then
        assert(native:playing() and p.play_state==2,'gameplay did not start')
        -- Select Master rules for the drop-input test after normal boot/start.
        s:write_u16(0x06064898+0x30c,2)
        start_y=p.active_y
        piece=p.active_piece
        writes=native.parameter_writes
    end
    if frame==3020 then
        assert(p.active_y==start_y and p.gravity==0,'base 0G did not hold the piece')
        press('P1 Down',true)
    end
    if frame==3025 then press('P1 Down',false) end
    if frame==3030 then
        soft_y=p.active_y
        assert(soft_y<start_y and soft_y>5*65536,'soft drop did not move the airborne piece')
    end
    if frame==3038 then
        assert(p.active_y==soft_y,'releasing Down did not restore 0G')
        press('P1 Up',true)
    end
    if frame==3040 then press('P1 Up',false) end
    if frame==3042 then
        assert(p.active_y<soft_y-5*65536 and p.active_y//65536<=2,'sonic drop did not reach the floor')
        assert(p.active_piece==piece and p.level==0 and (p.play_state==2 or p.play_state==3),'sonic drop unexpectedly locked immediately')
        assert(native:state(1).active_y==start_y,'P1 inputs affected P2')
        assert(native.parameter_writes==writes,'steady gameplay wrote trainer parameters')
        print(string.format('DROP PASS: base 0G y=%d; soft drop y=%d; release holds; sonic drop y=%d; P2 stationary; no parameter rewrites',start_y//65536,soft_y//65536,p.active_y//65536))
    end
end)
