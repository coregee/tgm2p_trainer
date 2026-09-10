-- Test-only opening-preview and real tap/DAS movement regression fixture.
local json=require('json')
local prefix=assert(os.getenv('TGM_TEST_PLUGIN'))
local output=assert(os.getenv('TGM_TEST_OUTPUT'))
local selected=assert(os.getenv('TGM_TEST_BIG_PLAYERS'))
local function load(name)
    local f=assert(io.open(prefix..'/'..name)); local data=json.parse(f:read('a')); f:close(); return data
end
local s=manager.machine.devices[':maincpu'].spaces.program
local native=dofile(prefix..'/native.lua').new(s,load('native.json'),load('catalog.json'))
local choices={tonumber(selected:sub(1,1)),tonumber(selected:sub(2,2))}
local function publish()
    native:sync({players={{gravity=0,big=choices[1],das=4},{gravity=0,big=choices[2],das=4}},global={}})
end
publish()
dofile(assert(os.getenv('TGM_TEST_GAMEPLAY')))
local fields={}
for _,port in pairs(manager.machine.ioport.ports) do
    for name,field in pairs(port.fields) do fields[name]=field end
end
local function press(p,key,on) assert(fields['P'..(p+1)..' '..key],key):set_value(on and 1 or 0) end
local frame=0
local started,preview,previous,moves,done={},{},{},{},{}
local visible_preview={}
_G.big_probe=emu.add_machine_frame_notifier(function()
    frame=frame+1
    native:install(); assert(not native.error,native.error)
    if not native:playing() or frame<1900 then return end
    for p=0,1 do
        local st=native:state(p)
        local big=tonumber(selected:sub(p+1,p+1))
        local step=big==1 and 2 or 1
        if not visible_preview[p] and st.play_state==10 and s:read_u32(0x06064898+p*0x3b4+0x308)&0x40000~=0 then
            visible_preview[p]=frame+1
        end
        if visible_preview[p]==frame then
            manager.machine.screens[':screen']:snapshot(output..'/ready-p'..(p+1)..'.png')
        end
        if not preview[p] and st.play_state==10 and st.next_piece&15>=2 then
            assert((st.next_piece&0x200~=0)==(big==1),'opening preview flag P'..(p+1))
            preview[p]=true
            manager.machine.screens[':screen']:snapshot(output..'/preview-p'..(p+1)..'.png')
        end
        if not started[p] and st.play_state==2 then
            assert((st.active_piece&0x200~=0)==(big==1),'first active flag P'..(p+1))
            assert(st.game_mode&0x40==0,'trainer forged BIG game mode')
            assert(st.active_x==(big==1 and 5 or 4),'spawn alignment P'..(p+1)..': '..st.active_x)
            started[p]=frame; previous[p]=st.active_x; moves[p]=0
            print(string.format('FIRST P%d active=%x next=%x x=%d',p+1,st.active_piece,st.next_piece,st.active_x))
        end
        if started[p] and not done[p] then
            local age=frame-started[p]
            local delta=math.abs(st.active_x-previous[p])
            assert(delta==0 or delta==step,'wrong movement step P'..(p+1)..': '..delta)
            if delta>0 then moves[p]=moves[p]+1 end
            previous[p]=st.active_x
            if age==10 then press(p,'Right',true) end
            if age==12 then press(p,'Right',false) end
            if age==20 then press(p,'Left',true) end
            if age==22 then press(p,'Left',false) end
            if age==30 then press(p,'Right',true) end
            if age==80 then press(p,'Right',false) end
            if age==82 then press(p,'Left',true) end
            if age==132 then press(p,'Left',false) end
            -- A queue change must not change the current piece's movement grid.
            if age==136 then choices[p+1]=1-big; publish() end
            if age==140 then press(p,'Right',true) end
            if age==150 then press(p,'Right',false) end
            if age==154 then
                assert(moves[p]>=3,'movement did not exercise the grid')
                assert(preview[p],'opening preview not observed')
                assert(visible_preview[p],'opening preview renderer not enabled')
                assert((st.active_piece&0x200~=0)==(big==1),'mid-piece geometry changed')
                assert((st.next_piece&0x200~=0)==(big==0),'queued toggle did not change')
                done[p]=true
                print(string.format('BIG PASS P%d: opening preview, first piece, spawn alignment, %d tap/DAS moves of %d columns, mid-piece toggle preserves grid',p+1,moves[p],step))
            end
        end
    end
end)
