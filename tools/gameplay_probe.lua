-- Test-only MAME autoboot script: coin/start input and screenshots.
local frame = 0

local fields = {}
for tag, port in pairs(manager.machine.ioport.ports) do
    for name, field in pairs(port.fields) do
        fields[name] = field
    end
end
local function press(name, down)
    if fields[name] then fields[name]:set_value(down and 1 or 0) end
end
local sub
sub = emu.add_machine_frame_notifier(function()
    frame = frame + 1
    if frame == 1800 then press("Coin 1", true); press("Coin 2", true) end
    if frame == 1805 then press("Coin 1", false); press("Coin 2", false) end
    if frame == 1860 then press("1 Player Start", true); press("2 Players Start", true) end
    if frame == 1865 then press("1 Player Start", false); press("2 Players Start", false) end
    if frame == 1980 then press("P1 Button 1", true); press("P2 Button 1", true) end
    if frame == 1985 then press("P1 Button 1", false); press("P2 Button 1", false) end
    if frame == 2050 then press("Coin 2", true) end
    if frame == 2055 then press("Coin 2", false) end
    if frame == 2180 then press("2 Players Start", true) end
    if frame == 2185 then press("2 Players Start", false) end
    if frame == 2340 then press("P2 Button 1", true) end
    if frame == 2345 then press("P2 Button 1", false) end
    if frame % 120 == 0 then
        local s = manager.machine.devices[":maincpu"].spaces.program
        print(string.format("GAME %d state=%d level=%d y=%d mode=%x pc=%x", frame,
            s:read_u8(0x06064bf5),s:read_u16(0x06064bba),s:read_u16(0x06064c00),
            s:read_u16(0x06064ba4),manager.machine.devices[":maincpu"].state.PC.value))
    end
    if frame == 2400 and os.getenv("TGM_TRAINER_SNAPSHOT") then
        manager.machine.screens[":screen"]:snapshot(os.getenv("TGM_TRAINER_SNAPSHOT"))
    end
end)
_G.tgm_gameplay_probe = {sub, emu.add_machine_reset_notifier(function() frame=0 end)}
