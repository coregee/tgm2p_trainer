-- Test-only seeded full rows, followed by real piece locks and line clears.
local json=require('json')
local prefix=assert(os.getenv('TGM_TEST_PLUGIN'))
local selected=assert(os.getenv('TGM_TEST_BIG_PLAYERS'))
local function load(name)
    local f=assert(io.open(prefix..'/'..name)); local data=json.parse(f:read('a')); f:close(); return data
end
local s=manager.machine.devices[':maincpu'].spaces.program
local native=dofile(prefix..'/native.lua').new(s,load('native.json'),load('catalog.json'))
local players={{effective_gravity=0,lock=1},{effective_gravity=0,lock=1}}
for p=1,2 do players[p].big=tonumber(selected:sub(p,p)) end
local function publish() native:sync(json.parse(json.stringify({players=players,global={}}))) end
publish()
dofile(assert(os.getenv('TGM_TEST_GAMEPLAY')))
local frame=0
local cases,phase,prior,begin,clears={1,1},{},{},{},{}
_G.big_lines_probe=emu.add_machine_frame_notifier(function()
    frame=frame+1
    native:install(); assert(not native.error,native.error)
    if frame<3100 or not native:playing() then return end
    for p=0,1 do
        local i=p+1
        local b=0x06064898+p*0x3b4
        local st=native:state(p)
        local variant=tonumber(selected:sub(i,i))
        local n=cases[i]
        if n<=6 and not phase[i] and st.play_state==2 then
            local count=n<=4 and n or 4
            local rows=variant>0 and count*2 or count
            local field=s:read_u32(b)
            local width=s:read_u8(b+0xdf)
            local height=s:read_u8(b+0xde)
            for y=1,height-2 do
                for x=1,width-2 do
                    local cell=field+(y*width+x)*6
                    s:write_u16(cell,y<=rows and 8 or 0)
                    s:write_u16(cell+4,0)
                end
            end
            -- Cases 5/6 exercise section crossing and freeze precedence.
            local level=n==5 and 98 or 100
            players[i].freeze_level=n==6 and 1 or nil
            players[i].big=variant
            publish()
            native:action('level',p,level)
            prior[i]=level
            begin[i]=frame
            clears[i]=false
            -- Changing the desired variant mid-piece must not change this clear.
            players[i].big=variant==2 and 3 or 2
            players[i].effective_gravity=1310720
            publish()
            phase[i]='lock'
            print(string.format('SEED P%d variant=%d case=%d rows=%d level=%d latch=%d width=%d height=%d',i,variant,n,rows,level,s:read_i32(0x060ef040+p*256),width,height))
        elseif phase[i] then
            if st.play_state==3 then
                players[i].effective_gravity=0
                players[i].big=variant
                publish()
            end
            if st.play_state==4 then clears[i]=true end
            if st.play_state==5 and clears[i] then
                local count=n<=4 and n or 4
                local gain=(variant==1 or variant==2) and count*2 or count
                if n==6 then gain=0 end
                assert(st.level==prior[i]+gain,string.format('P%d variant=%d case=%d expected level=%d got=%d',i,variant,n,prior[i]+gain,st.level))
                if n==5 then assert(st.section==1,'section crossing bookkeeping') end
                print(string.format('LINES PASS P%d variant=%d case=%d gain=%d',i,variant,n,gain))
                cases[i]=n+1; phase[i]=nil
            end
            assert(frame-begin[i]<240,'line clear timed out P'..i..' state='..st.play_state)
        end
    end
end)
