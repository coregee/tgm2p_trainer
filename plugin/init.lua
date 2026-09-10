-- Protocol 3: complete desired snapshots, explicit actions, read-only telemetry.
local exports={name='tgm2p-trainer',version='0.4.0',description='Native TGM2+ trainer',
    license='BSD-3-Clause',author={name='coregee'}}
local folder
function exports.set_folder(path) folder=path end
function exports.startplugin()
    local json=require('json')
    local function load(name)
        local f=assert(io.open(folder..'/'..name,'r'))
        local data=f:read('a'); f:close()
        return assert(json.parse(data))
    end
    local catalog=load('catalog.json')
    local manifest=load('native.json')
    local Native=dofile(folder..'/native.lua')
    local native,space
    local frame,revision=0,0
    local desired={players={{},{}},global={}}
    local socket,connected,rx=nil,false,''
    local function listen()
        if socket then pcall(function() socket:close() end) end
        socket=emu.file('',7)
        local err=socket:open('socket.127.0.0.1:'..catalog.port)
        if err then emu.print_error('Trainer cannot listen: '..tostring(err)) end
        connected=false; rx=''
    end
    local function send(message)
        if not connected then return end
        local data=json.stringify(message)..'\n'
        local ok,n=pcall(function() return socket:write(data) end)
        if not ok or n~=#data then listen() end
    end
    local input=dofile(folder..'/input.lua').new(send)
    local function status()
        return {t='status',ready=native and native.ready or false,
            error=native and native.error,revision=revision,
            installs=native and native.installs or 0,
            parameter_writes=native and native.parameter_writes or 0,
            action_writes=native and native.action_writes or 0,
            drc=manager.options.entries.drc:value()}
    end
    local function handle(m)
        assert(type(m)=='table' and type(m.t)=='string','expected command object')
        if m.t=='hello' then
            send({t='hello',protocol=3,version=exports.version,rom=emu.romname(),
                compatible=emu.romname()=='tgm2p',catalog=catalog,patch_id=manifest.sha256})
            send(status())
        elseif m.t=='sync' then
            assert(native,'unsupported game')
            native:sync(m.settings)
            desired=m.settings
            revision=m.id or revision
            send({t='ack',id=m.id,ready=native.ready,settings=desired})
        elseif m.t=='action' then
            assert(native,'unsupported game')
            native:action(m.action,m.player,m.value)
            send({t='ack',id=m.id,action=m.action})
        elseif m.t=='bindings' then
            assert(type(m.bindings)=='table' and #m.bindings<=32,'invalid bindings')
            for _,b in ipairs(m.bindings) do
                assert(type(b)=='table' and type(b.action)=='string' and type(b.token)=='string' and #b.token<64,'invalid binding')
                assert(b.mods==nil or type(b.mods)=='table','invalid modifiers')
                for _,mod in ipairs(b.mods or {}) do assert(mod=='ctrl' or mod=='shift' or mod=='alt' or mod=='win','invalid modifier') end
            end
            input.set(m.bindings)
            send({t='ack',id=m.id})
        elseif m.t=='reset_machine' then
            manager.machine:soft_reset()
            send({t='ack',id=m.id,action=m.t})
        elseif m.t=='ping' then
            send({t='heartbeat',ready=native and native.ready or false,paused=manager.machine.paused})
        elseif m.t=='diagnostics' then
            local s=status(); s.id=m.id; send(s)
        else error('unknown command: '..m.t) end
    end
    local function pump()
        for _=1,4 do
            local chunk=socket:read(4096)
            if not chunk or #chunk==0 then break end
            connected=true
            rx=rx..chunk
            if #rx>65536 then listen(); return end
        end
        for _=1,64 do
            local n=rx:find('\n',1,true)
            if not n then break end
            local line=rx:sub(1,n-1); rx=rx:sub(n+1)
            local m=json.parse(line)
            local ok,err=pcall(handle,m)
            if not ok then send({t='error',id=type(m)=='table' and m.id or nil,msg=tostring(err)}) end
        end
    end
    local function acquire()
        local cpu=manager.machine.devices[':maincpu']
        space=cpu and cpu.spaces.program
        if space and emu.romname()=='tgm2p' then
            if not native then native=Native.new(space,manifest,catalog) end
            native.space=space
            native:invalidate()
            native.desired=desired
        end
    end
    local function emit_state()
        if native and native.ready then
            local music=space:read_u8(0x06064767)
            send({t='state',frame=frame,revision=revision,ready=true,
                playing=native:playing(),
                players={native:state(0),native:state(1)},music=music==255 and -1 or music,music_scene=space:read_i16(0x06064892),
                settings=desired})
        end
    end
    local reset=emu.add_machine_reset_notifier(acquire)
    local postload=emu.add_machine_post_load_notifier(function()
        acquire() -- saved code/settings can be stale; validate and republish desired state
    end)
    local stopped=emu.add_machine_stop_notifier(function()
        if socket then socket:close() end
        native=nil; space=nil
    end)
    local tick=emu.add_machine_frame_notifier(function()
        frame=frame+1
        if not space then acquire() end
        pump()
        input.poll()
        if native and not native.ready and not native.error then
            native:install()
            if native.ready or native.error then send(status()) end
        end
        if frame%6==0 then emit_state() end
        if frame%30==0 then
            send({t='heartbeat',ready=native and native.ready or false,paused=manager.machine.paused})
        end
    end)
    exports._subscriptions={reset,postload,stopped,tick}
    emu.register_periodic(function()
        if space and manager.machine.paused then pump(); emit_state() end
    end)
    listen()
end
return exports
