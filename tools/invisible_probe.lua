-- Test-only real lock/render fixture. Canonical runs select the game's M-roll
-- mode/qualification; override runs use ordinary gameplay and trainer settings.
local json=require('json')
local prefix=assert(os.getenv('TGM_TEST_PLUGIN'))
local output=assert(os.getenv('TGM_TEST_OUTPUT'))
local canonical=os.getenv('TGM_TEST_CANONICAL')=='1'
local doubles=os.getenv('TGM_TEST_DOUBLES')=='1'
local big=os.getenv('TGM_TEST_BIG')=='1'
local fading=os.getenv('TGM_TEST_FADING')=='1'
local function load(name)
    local f=assert(io.open(prefix..'/'..name)); local data=json.parse(f:read('a')); f:close(); return data
end
local s=manager.machine.devices[':maincpu'].spaces.program
local native=dofile(prefix..'/native.lua').new(s,load('native.json'),load('catalog.json'))
local function publish(gravity)
    native:sync({players={
        {effective_gravity=gravity,lock=20,invisible=not canonical and (fading and 2 or 1) or nil},
        {effective_gravity=0}},global={}})
end
publish(0)
dofile(assert(os.getenv('TGM_TEST_GAMEPLAY')))
local frame=0
local tracked,first
local trace={}
_G.invisible_probe=emu.add_machine_frame_notifier(function()
    frame=frame+1
    native:install()
    assert(not native.error,native.error)
    if doubles and frame==2800 then
        s:write_u32(0x06064880,4)
        for p=0,1 do
            local b=0x06064898+p*0x3b4
            s:write_u16(b+0x30c,4)
            s:write_u32(b+0x308,0x3004)
        end
    end
    local b=0x06064898
    local renderer=doubles and 0x06064c4c or b
    if frame==3100 then
        assert(native:playing(),'gameplay did not start')
        assert(native:state(0).play_state==2,'P1 not active')
        if canonical then
            s:write_u16(b+0x30c,s:read_u16(b+0x30c)|0x10)
            s:write_u8(b+0x338,fading and 0 or 0x75)
        end
        -- Lift the landing surface into clear view, away from the bottom HUD.
        local field=s:read_u32(renderer)
        local width=s:read_u8(renderer+0xdf)
        for y=1,5 do
            for x=2,width-2 do s:write_u16(field+(y*width+x)*6,8) end
        end
        if big then s:write_u16(b+0x35e,s:read_u16(b+0x35e)|0x200) end
        publish(1310720)
    end
    if frame>=3100 and not tracked then
        local field=s:read_u32(renderer)
        local width=s:read_u8(renderer+0xdf)
        local height=s:read_u8(renderer+0xde)
        for index=0,width*height-1 do
            local cell=field+index*6
            if s:read_u16(cell)&0x80~=0 then
                tracked=cell; first=frame
                publish(0) -- Keep later pieces away from the cell being measured.
                local f=assert(io.open(output..'/cell.json','w'))
                f:write(json.stringify({
                    x=s:read_u16(renderer+0x314)+s:read_u16(renderer+0xe0)-width*4+(index%width)*8,
                    y=s:read_u16(renderer+0x316)+s:read_u16(renderer+0xe2)-(index//width)*8-6}))
                f:close()
                print(string.format('LOCK frame=%d index=%d width=%d cell=%x',frame,index,width,cell))
                break
            end
        end
    end
    local last=fading and 307 or 9
    if tracked and frame-first<=last then
        local n=frame-first
        local attr=s:read_u16(tracked)
        local timer=s:read_u16(tracked+4)
        trace[#trace+1]={frame=n,attr=attr,timer=timer}
        print(string.format('INVISIBLE %d attr=%04x timer=%d',n,attr,timer))
        if n<6 or n>last-14 then manager.machine.screens[':screen']:snapshot(output..'/'..n..'.png') end
        if n==last then
            local f=assert(io.open(output..'/trace.json','w')); f:write(json.stringify(trace)); f:close()
            print('INVISIBLE PASS')
        end
    end
end)
