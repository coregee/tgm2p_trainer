-- Read-only boot diagnostics; run without the trainer to see unpatched RAM.
local frame = 0
local sub
sub = emu.add_machine_frame_notifier(function()
    frame = frame + 1
    if frame % 60 == 0 then
        local s = manager.machine.devices[":maincpu"].spaces.program
        print(string.format("PROBE %d pc=%08x renderer=%08x gravity_ptr=%08x state=%d level=%d", frame,
            manager.machine.devices[":maincpu"].state.PC.value,
            s:read_u32(0x06002558), s:read_u32(0x06007c5c),
            s:read_u8(0x06064bf5), s:read_u16(0x06064bba)))
    end
end)
_G.tgm_boot_probe = sub
