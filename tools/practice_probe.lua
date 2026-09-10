-- Test-only fixture: enter Doubles through normal player initialization, seed
-- a known stack, then exercise P1 control of the shared P2 renderer. Never
-- loaded by the production launcher. Paths are supplied by verify_practice.py.
local json=require('json')
local prefix=assert(os.getenv('TGM_TEST_PLUGIN'))
local output=assert(os.getenv('TGM_TEST_OUTPUT'))
local function load(name)
    local f=assert(io.open(prefix..'/'..name)); local data=json.parse(f:read('a')); f:close(); return data
end
local s=manager.machine.devices[':maincpu'].spaces.program
local native=dofile(prefix..'/native.lua').new(s,load('native.json'),load('catalog.json'))
local settings={players={{effective_gravity=0},{effective_gravity=0}},global={}}
native:sync(settings)
dofile(assert(os.getenv('TGM_TEST_GAMEPLAY')))
local frame=0
local function publish(invisible)
    -- Build a new snapshot: Native deliberately retains the previous snapshot.
    settings={players={{effective_gravity=0,invisible=invisible},{effective_gravity=0}},global={}}
    native:sync(settings)
end
_G.practice_probe=emu.add_machine_frame_notifier(function()
    frame=frame+1
    native:install()
    assert(not native.error,native.error)
    if frame==2800 then
        assert(native:playing(),'real gameplay did not start')
        s:write_u32(0x06064880,4)
        for p=0,1 do
            local b=0x06064898+p*0x3b4
            s:write_u16(b+0x30c,4)
            s:write_u32(b+0x308,0x3004)
        end
    end
    if frame==3100 then
        local b=0x06064c4c
        local field=s:read_u32(b)
        local width=s:read_u8(b+0xdf)
        local height=s:read_u8(b+0xde)
        assert(width>12,'Doubles field did not initialize: '..width)
        assert(native:state(1).play_state==2,'P2 not active')
        for x=1,width-2 do
            local cell=field+((height-2)*width+x)*6
            s:write_u16(cell,2+(x%7))
            s:write_u8(cell+2,0)
            s:write_u8(cell+3,0)
            s:write_u16(cell+4,0)
        end
        print('DOUBLES shared field width='..width..' height='..height)
    end
    if frame==3120 then manager.machine.screens[':screen']:snapshot(output..'/stock.png') end
    if frame==3140 then publish(1) end
    if frame==3160 then manager.machine.screens[':screen']:snapshot(output..'/hidden.png') end
    if frame==3180 then
        -- Expired timed-invisible cells must also be visible when forced on.
        local b=0x06064c4c
        local field=s:read_u32(b)
        local width=s:read_u8(b+0xdf)
        local height=s:read_u8(b+0xde)
        for x=1,width-2 do
            local cell=field+((height-2)*width+x)*6
            s:write_u16(cell,s:read_u16(cell)|0x5000)
        end
        publish(0)
    end
    if frame==3200 then
        manager.machine.screens[':screen']:snapshot(output..'/visible.png')
        local b=0x06064c4c
        local field=s:read_u32(b)
        local width=s:read_u8(b+0xdf)
        local height=s:read_u8(b+0xde)
        for x=1,width-2 do
            local cell=field+((height-2)*width+x)*6
            assert(s:read_u16(cell)&0x5000==0x5000,'visibility changed stored cell flags')
        end
    end
    if frame==3220 then publish(nil) end
    if frame==3240 then
        manager.machine.screens[':screen']:snapshot(output..'/released.png')
        print('PRACTICE PASS')
    end
end)
