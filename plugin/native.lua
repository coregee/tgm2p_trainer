-- Native patch lifecycle and parameter ABI. Game writes are only permitted
-- during installation, settings changes, explicit actions, and state reloads.
local Native = {}
Native.__index = Native

function Native.new(space, manifest, catalog)
    return setmetatable({space=space, manifest=manifest, catalog=catalog,
        ready=false, error=nil, installs=0, parameter_writes=0, action_writes=0,
        desired={players={{},{}},global={}}, applied=nil, original_items={}}, Native)
end

local function integer(v, min, max)
    return type(v)=="number" and v==math.floor(v) and v>=min and v<=max
end

function Native:validate(settings)
    assert(type(settings)=="table" and type(settings.players)=="table" and
        #settings.players==2 and type(settings.global)=="table", "expected two player settings and global settings")
    for k in pairs(settings) do assert(k=="players" or k=="global", "unknown settings group") end
    for _, player in ipairs(settings.players) do
        assert(type(player)=="table", "player settings must be objects")
        for key,value in pairs(player) do
            local c=self.catalog.controls[key]
            assert(c and integer(value,c.min,c.max), "invalid control: "..tostring(key))
        end
        assert(not (player.gravity and player.effective_gravity), "choose base or effective gravity")
    end
    for key,value in pairs(settings.global) do
        assert(key=="music" and integer(value,0,10), "invalid global control")
    end
end

function Native:bytes(addr, count)
    local t={}
    for i=0,count-1 do t[#t+1]=string.format("%02x",self.space:read_u8(addr+i)) end
    return table.concat(t)
end

function Native:write_bytes(addr, hex)
    for i=1,#hex,2 do self.space:write_u8(addr+(i-1)//2,tonumber(hex:sub(i,i+1),16)) end
end

function Native:install()
    if self.ready or self.error then return end
    -- Boot performs a RAM test and then copies the program. Wait for its last
    -- code region to be present before checking signatures or installing hooks.
    if self.space:read_u32(0x06002558)~=0x060161b8 then return end
    for _,patch in ipairs(self.manifest.patches) do
        local actual=self:bytes(patch.address,patch.size)
        if actual~=patch.expected and actual~=patch.bytes then
            self.error=string.format("Unsupported or modified code at %08X (%s)",patch.address,patch.name)
            return
        end
    end
    -- MAME runs Lua callbacks between CPU slices: the guest cannot observe
    -- partially published settings or a half-installed trampoline.
    self:write_bytes(self.manifest.base,self.manifest.payload)
    for p=0,1 do
        local runtime=self.manifest.parameters+p*256+64
        -- Keep the falling piece's rule when loading a state from this build.
        if self.space:read_u32(runtime+4)~=0x42494735 then
            self.space:write_u32(runtime,0xffffffff)
            self.space:write_u32(runtime+4,0x42494735)
        end
    end
    for _,patch in ipairs(self.manifest.patches) do self:write_bytes(patch.address,patch.bytes) end
    self.ready=true
    self.installs=self.installs+1
    self.applied=nil
    self:apply()
end

function Native:invalidate()
    self.ready=false
    self.error=nil
    self.applied=nil
end

function Native:set_level(p, value)
    local base=0x06064898+p*0x3b4
    self.space:write_u16(base+0x322,value)
    self.space:write_u16(base+0x38c,value//100)
    self.space:write_u8(base+0x346,value//100)
    if self.desired.players[p+1].freeze_level then
        self.space:write_u32(self.manifest.parameters+p*256+36,value)
        self.parameter_writes=self.parameter_writes+1
    end
    self.action_writes=self.action_writes+3
end

function Native:set_toggle(p, key, value)
    if not self:playing() then return end
    local b=0x06064898+p*0x3b4
    local addr=b+(key=='big' and 0x360 or 0x30c)
    local old=self.space:read_u16(addr)
    if key=='items' and self.original_items[p]==nil then self.original_items[p]=old&0x200 end
    self.space:write_u16(addr,value~=0 and (old|0x200) or (old&~0x200))
    self.action_writes=self.action_writes+1
end

function Native:apply()
    if not self.ready then return end
    local prior=self.applied
    for p=0,1 do
        local values=self.desired.players[p+1]
        local old=prior and prior.players[p+1] or {}
        local addr=self.manifest.parameters+p*256
        local flags=0
        if prior and old.big~=nil and values.big==nil and self:playing() then
            local b=0x06064898+p*0x3b4
            local natural=(self.space:read_u16(b+0x30c)&0x40)~=0 or (self.space:read_u16(b+0x37c)&1)~=0
            self:set_toggle(p,'big',natural and 1 or 0)
        end
        if prior and old.items~=nil and values.items==nil then
            self:set_toggle(p,'items',(self.original_items[p] or 0)~=0 and 1 or 0)
            self.original_items[p]=nil
        end
        for key,c in pairs(self.catalog.controls) do
            local value=values[key]
            if value~=nil then
                flags=flags|c.bit
                if not prior or value~=old[key] then
                    local parameter=value
                    if key=="freeze_level" then
                        parameter=self:playing() and self.space:read_u16(0x06064898+p*0x3b4+0x322) or 0
                    end
                    self.space:write_u32(addr+c.offset,parameter)
                    self.parameter_writes=self.parameter_writes+1
                    if key=="big" or key=="items" then self:set_toggle(p,key,value) end
                end
            end
        end
        if not prior or self.space:read_u32(addr)~=flags then
            self.space:write_u32(addr,flags)
            self.parameter_writes=self.parameter_writes+1
        end
    end
    local music=self.desired.global.music or -1
    if not prior or music~=(prior.global.music or -1) then
        self.space:write_u32(self.manifest.parameters+512,music&0xffffffff)
        self.parameter_writes=self.parameter_writes+1
    end
    self.applied=self.desired
end

function Native:sync(settings)
    self:validate(settings) -- complete validation precedes all mutation
    self.desired=settings
    self:apply()
end

function Native:action(key, p, value)
    -- Keep UI controls stable. Reject transient practice inputs silently at
    -- dispatch time, before any RAM access or write; never queue them to replay.
    local practice=key=="level" or key=="section" or key=="grade" or key=="restart"
    if practice and (not self.ready or not self:playing()) then return end
    assert(self.ready,"game is not ready")
    assert(integer(p,0,1),"invalid player")
    local base=0x06064898+p*0x3b4
    if key=="level" then
        assert(integer(value,0,999),"level must be 0..999")
        self:set_level(p,value)
    elseif key=="section" then
        assert(value==-1 or value==1,"section direction must be -1 or 1")
        local section=self.space:read_u16(base+0x322)//100
        self:set_level(p,math.max(0,math.min(9,section+value))*100)
    elseif key=="grade" then
        assert(integer(value,0,31),"grade must be 0..31")
        self.space:write_u8(0x06079378+p*0x4c,value)
        self.action_writes=self.action_writes+1
    elseif key=="restart" then
        self.space:write_u32(base+0x308,self.space:read_u32(base+0x308)|0x3000)
        self.action_writes=self.action_writes+1
    elseif key=="debug" then
        assert(integer(value,0,1),"flag must be 0 or 1")
        self.space:write_u8(0x0607cf0c,value)
        self.action_writes=self.action_writes+1
    else error("unknown action") end
end

function Native:playing()
    return self.space:read_u16(0x06060022)==1
end

function Native:state(p)
    local s=self.space
    local b=0x06064898+p*0x3b4
    return {level=s:read_u16(b+0x322),section=s:read_u16(b+0x38c),
        section_count=s:read_u8(b+0x346),play_state=s:read_u8(b+0x35d),
        game_mode=s:read_u16(b+0x30c),gravity=s:read_u32(b+0x358),
        active_x=s:read_i16(b+0x364),active_y=s:read_i32(b+0x368),
        active_piece=s:read_u16(b+0x35e),next_piece=s:read_u16(b+0x360),
        lock_remaining=s:read_u8(b+0x347),lock_duration=s:read_u8(b+0x348),
        das_charge=s:read_u8(b+0x349),delay_remaining=s:read_u16(b+0x300),
        grade=s:read_u8(0x06079378+p*0x4c),timer=s:read_u32(b+0x350)}
end

return Native
