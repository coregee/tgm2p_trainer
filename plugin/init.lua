-- P1: p=0; P2: p=1

local exports = {
	name = "tgm2p-trainer",
	version = "0.1.0",
	description = "TGM2 Trainer bridge",
	license = "BSD-3-Clause",
	author = { name = "coregee" } }

local tgmtrainer = exports

local plugin_dir
function tgmtrainer.set_folder(path) plugin_dir = path end

function tgmtrainer.startplugin()
	local json = require("json")

	local MAP = {} -- addresses.json
	local PORT = 50575

	local function load_config()
		local path = (plugin_dir or ".") .. "/addresses.json"
		local file = io.open(path, "r")
		if not file then
			emu.print_error("tgm2p-trainer: cannot open " .. path)
			return false, "cannot open " .. path
		end
		local text = file:read("a")
		file:close()
		local parsed, _, err = json.parse(text)
		if not parsed then
			emu.print_error("tgm2p-trainer: bad addresses.json: " .. tostring(err))
			return false, "parse error: " .. tostring(err)
		end
		MAP = parsed
		MAP.addresses  = MAP.addresses  or {}
		MAP.composites = MAP.composites or {}
		MAP.recipes    = MAP.recipes    or {}
		MAP.tables     = MAP.tables     or {}
		MAP.celldim    = MAP.celldim    or {}
		MAP.dasfx      = MAP.dasfx      or {}
		MAP.codepatches = MAP.codepatches or {}
		if MAP.meta and MAP.meta.port then PORT = MAP.meta.port end
		return true
	end

	local cpu, space

	local function acquire_cpu()
		cpu = manager.machine.devices[":maincpu"]
		space = cpu and cpu.spaces["program"] or nil
	end

	local function addr_of(key)
		local d = MAP.addresses[key]
		if not d then error("unknown address key: " .. tostring(key)) end
		local a = tonumber(d.address)
		if not a then error("address for '" .. key .. "' not set (placeholder " .. tostring(d.address) .. ") - discover it and edit addresses.json") end
		return a, d
	end

	local function read_raw(a, size)
		if size == 1 then return space:read_u8(a)
		elseif size == 2 then return space:read_u16(a)
		else return space:read_u32(a) end
	end

	-- Return address shifted to target player (from P1 base)
	local function player_addr(a, p)
		if not p or p <= 0 then return a end
		local pl = MAP.meta and MAP.meta.players
		if pl and pl.structs then
			for _, s in ipairs(pl.structs) do
				local base, size = tonumber(s.base), tonumber(s.size)
				if a >= base and a < base + size then return a + p * tonumber(s.stride) end
			end
		end
		return a
	end

	local function read_named(key, player)
		local a, d = addr_of(key)
		a = player_addr(a, player)
		if d.mask then return ((read_raw(a, d.size) & tonumber(d.mask)) ~= 0) and 1 or 0 end
		local signed = (d.type == "s")
		if d.size == 1 then return signed and space:read_i8(a)  or space:read_u8(a)
		elseif d.size == 2 then return signed and space:read_i16(a) or space:read_u16(a)
		else                   return signed and space:read_i32(a) or space:read_u32(a) end
	end

	local function write_named(key, v, player)
		local a, d = addr_of(key)
		a = player_addr(a, player)
		v = math.floor(v + 0.0)
		if d.min and v < d.min then v = d.min end
		if d.max and v > d.max then v = d.max end
		if d.readonly then error("'" .. key .. "' is read-only") end
		if d.mask then
			local m = tonumber(d.mask)
			local raw = read_raw(a, d.size)
			v = (v ~= 0) and (raw | m) or (raw & ~m)
		end
		if d.size == 1 then space:write_u8(a, v & 0xff)
		elseif d.size == 2 then space:write_u16(a, v & 0xffff)
		else                   space:write_u32(a, v & 0xffffffff) end
	end

	local function apply_also_or(d, players, on)
		if not (d and d.also_or and space) then return end
		for _, p in ipairs(players or { 0 }) do
			for _, e in ipairs(d.also_or) do
				local a = player_addr(tonumber(e.address), p)
				local sz = tonumber(e.size) or 2
				local m = tonumber(e.mask)
				local raw = read_raw(a, sz)
				local nv = on and (raw | m) or (raw & ~m)
				if sz == 1 then space:write_u8(a, nv & 0xff)
				elseif sz == 2 then space:write_u16(a, nv & 0xffff)
				else                   space:write_u32(a, nv & 0xffffffff) end
			end
		end
	end

	local function classify(key)
		if MAP.addresses[key]  then return "address" end
		if MAP.composites[key] then return "composite" end
		if MAP.recipes[key]    then return "recipe" end
		if MAP.tables[key]     then return "table" end
		if MAP.celldim[key]    then return "celldim" end
		if MAP.dasfx[key]      then return "das" end
		return nil
	end

	-- "celldim": per-cell invisible function
	local function celldim_apply(c, set, player)
		-- base is player-defined; doubles uses P2
		local base = player_addr(tonumber(c.base), player)
		-- Reveal in non-play states (i.e., fading)
		if set and c.play_state_off and c.reveal_states then
			local ps = read_raw(base + tonumber(c.play_state_off), 1)
			for _, s in ipairs(c.reveal_states) do
				if ps == s then set = false break end
			end
		end
		local fb = read_raw(base + (tonumber(c.field_ptr_off) or 0), 4)
		if not (fb >= 0x06000000 and fb < 0x06100000) then return -1 end -- cell oob
		local w = read_raw(base + tonumber(c.width_off), 1)
		local h = read_raw(base + tonumber(c.height_off), 1)
		if not (w > 2 and w <= 32 and h > 2 and h <= 48) then return -2 end
		local stride = tonumber(c.stride) or 6
		local toff   = tonumber(c.type_off) or 0
		local tmask  = tonumber(c.type_mask) or 0xf
		local tmin   = tonumber(c.type_min) or 2
		local or16   = tonumber(c.or16)
		local coff   = tonumber(c.cell_off) or 0
		local attr   = tonumber(c.attr_off) or 2
		local onv, offv = tonumber(c.on_value) or 0, tonumber(c.off_value) or 5
		local n = 0
		for row = 1, h - 2 do
			local rb = fb + row * w * stride
			for col = 1, w - 2 do
				local a = rb + col * stride
				if (space:read_u16(a + toff) & tmask) >= tmin then -- locked piece
					if or16 then
						local v = space:read_u16(a + coff)
						space:write_u16(a + coff, (set and (v | or16) or (v & ~or16)) & 0xffff)
					else
						space:write_u8(a + attr, (set and onv or offv) & 0xff)
					end
					n = n + 1
				end
			end
		end
		return n
	end

	local function write_code_bytes(addr, hex)
		local a, j = tonumber(addr), 0
		for c = 1, #hex, 2 do
			space:write_u8(a + j, tonumber(hex:sub(c, c + 1), 16)); j = j + 1
		end
	end

	local function apply_codepatch(cp)
		if not (cp and cp.patches and space) then return end
		for _, p in ipairs(cp.patches) do
			if p.addr and p.bytes then write_code_bytes(p.addr, p.bytes) end
		end
		if cp.live_byte then space:write_u8(tonumber(cp.live_byte), 0) end
	end

	local function set_live_byte(addr, on)
		if addr and space then space:write_u8(tonumber(addr), on and 1 or 0) end
	end

	local function validate_override(key, value)
		local kind = classify(key)
		if not kind then return false, "unknown override key: " .. tostring(key) end
		if kind == "address" then
			local ok, err = pcall(addr_of, key)
			if not ok then return false, tostring(err) end
			if MAP.addresses[key].readonly then return false, "'" .. key .. "' is read-only" end
		elseif kind == "composite" then
			if type(value) ~= "table" then return false, "composite '" .. key .. "' needs an object value" end
			for _, m in ipairs(MAP.composites[key].members) do
				if value[m] ~= nil then
					local ok, err = pcall(addr_of, m)
					if not ok then return false, "member " .. tostring(err) end
				end
			end
		elseif kind == "recipe" then
			for _, w in ipairs(MAP.recipes[key].writes) do
				local ok, err = pcall(addr_of, w.name)
				if not ok then return false, "recipe " .. tostring(err) end
			end
		elseif kind == "table" then
			if type(value) ~= "number" then return false, "table '" .. key .. "' needs a numeric value" end
			local t = MAP.tables[key]
			if not (t.scratch and t.pointers and t.entries) then
				return false, "table '" .. key .. "' missing scratch/pointers/entries"
			end
		elseif kind == "celldim" then
			if type(value) ~= "number" then return false, "celldim '" .. key .. "' needs a numeric value" end
			local c = MAP.celldim[key]
			if not (c.base and c.width_off and c.height_off) then
				return false, "celldim '" .. key .. "' missing base/width_off/height_off"
			end
		elseif kind == "das" then
			if type(value) ~= "number" then return false, "das '" .. key .. "' needs a numeric value" end
			local d = MAP.dasfx[key]
			if not (d.scratch and d.game_mode and d.level and d.stock) then
				return false, "das '" .. key .. "' missing scratch/game_mode/level/stock"
			end
		end
		return true
	end

	local table_filled = {}

	local function apply_override(key, value, players)
		local kind = classify(key)
		local pl = players or { 0 } 
		if kind == "address" then
			for _, p in ipairs(pl) do write_named(key, value, p) end
			apply_also_or(MAP.addresses[key], pl, value ~= 0)
		elseif kind == "composite" then
			for _, p in ipairs(pl) do
				for _, m in ipairs(MAP.composites[key].members) do
					if value[m] ~= nil then write_named(m, value[m], p) end
				end
			end
		elseif kind == "recipe" then
			for _, p in ipairs(pl) do
				for _, w in ipairs(MAP.recipes[key].writes) do write_named(w.name, w.value, p) end
			end
		elseif kind == "table" then
			local t = MAP.tables[key]
			local scratch = tonumber(t.scratch)
			local sz = t.entry_size or 4
			local n  = t.entries
			local region = n * sz
			local offs = t.index_offsets
			local pass = (value == nil) or (value < 0)
			local fill
			if not pass then
				local v = math.floor(value + 0.0)
				if t.min and v < t.min then v = t.min end
				if t.max and v > t.max then v = t.max end
				fill = v * (t.scale or 1)
			end
			local flat = false
			if t.flat_when then
				local fa = tonumber(t.flat_when.addr)
				if fa then flat = (read_raw(fa, 2) & (tonumber(t.flat_when.mask) or 0)) ~= 0 end
			end
			local function stock(pi, idx)
				local off = (offs and offs[pi]) or 0
				local src = t.originals and tonumber(t.originals[pi])
				if off < 0 then
					if idx < -off or flat then return tonumber(t.below_default) or 0 end
					return src and read_raw(src + (idx + off) * sz, sz) or 0
				end
				return src and read_raw(src + idx * sz, sz) or 0
			end
			local function entry(pi, idx) return pass and stock(pi, idx) or fill end
			local state = pass and ("pass" .. (flat and "F" or "")) or fill
			if table_filled[key] ~= state or read_raw(scratch, sz) ~= entry(1, 0) then
				for pi = 1, #t.pointers do
					local base = scratch + (pi - 1) * region
					for i = 0, n - 1 do
						local o, w = i * sz, entry(pi, i)
						if sz == 1 then space:write_u8(base + o, w & 0xff)
						elseif sz == 2 then space:write_u16(base + o, w & 0xffff)
						else space:write_u32(base + o, w & 0xffffffff) end
					end
				end
				table_filled[key] = state
			end
			for pi = 1, #t.pointers do
				local off = (offs and offs[pi]) or 0
				local base = scratch + (pi - 1) * region
				space:write_u32(tonumber(t.pointers[pi]), (base - off * sz) & 0xffffffff)
			end
			if t.patches then
				for _, p in ipairs(t.patches) do
					local a, hex, j = tonumber(p.addr), p.bytes, 0
					for c = 1, #hex, 2 do
						space:write_u8(a + j, tonumber(hex:sub(c, c + 1), 16)); j = j + 1
					end
				end
			end
		elseif kind == "das" then
			local d = MAP.dasfx[key]
			if d.patches then
				for _, p in ipairs(d.patches) do
					local a, hex, j = tonumber(p.addr), p.bytes, 0
					for c = 1, #hex, 2 do
						space:write_u8(a + j, tonumber(hex:sub(c, c + 1), 16)); j = j + 1
					end
				end
			end
			local b
			if (value == nil) or (value < 0) then	-- override off
				local mode  = read_raw(tonumber(d.game_mode), 2)
				local level = read_raw(tonumber(d.level), 2)
				local s = d.stock
				if mode & tonumber(d.tgmplus_mask) ~= 0 then
					b = s.tgmplus
				else
					local band = (mode & tonumber(d.death_mask) ~= 0) and s.death or s.master
					b = band[#band][2]
					for _, pr in ipairs(band) do if level >= pr[1] then b = pr[2]; break end end
				end
			else  -- override on
				b = math.floor(value + 0.0)
				local lo, hi = d.min or 0, d.max or 127
				if b < lo then b = lo elseif b > hi then b = hi end
			end
			space:write_u8(tonumber(d.scratch), b & 0xff)
		elseif kind == "celldim" then
			if value ~= 0 then
				local c = MAP.celldim[key]
				local dbl = c.doubles_mode_addr
					and (read_raw(tonumber(c.doubles_mode_addr), 4) & tonumber(c.doubles_mask or "0x4")) ~= 0
				if dbl and c.doubles_live_byte then  -- doubles handler
					local dp = tonumber(c.doubles_player) or 1
					local reveal = false
					if c.play_state_off and c.reveal_states then
						local nplayers = (MAP.meta.players and MAP.meta.players.count) or 2
						for pp = 0, nplayers - 1 do
							local ps = read_raw(player_addr(tonumber(c.base), pp) + tonumber(c.play_state_off), 1)
							for _, s in ipairs(c.reveal_states) do if ps == s then reveal = true break end end
							if reveal then break end
						end
					end
					set_live_byte(c.doubles_live_byte, not reveal)
					if reveal then pcall(celldim_apply, c, false, dp) end
				elseif dbl then
					celldim_apply(c, true, tonumber(c.doubles_player) or 1)
				else
					if c.doubles_live_byte then set_live_byte(c.doubles_live_byte, false) end
					for p = 0, (MAP.meta.players and MAP.meta.players.count or 1) - 1 do
						celldim_apply(c, true, p)
					end
				end
			end
		end
	end

	local function is_sticky(key)
		if MAP.tables[key] then return true end
		local d = MAP.addresses[key]
		return d ~= nil and d.volatile ~= true
	end

	local socket = emu.file("", 7)       -- READ|WRITE|CREATE
	local socket_ok = false
	local have_client = false
	local rx_buffer = ""

	local function open_socket()
		local uri = string.format("socket.127.0.0.1:%d", PORT)
		local ok = pcall(function() socket:open(uri) end)
		socket_ok = ok
		if ok then emu.print_verbose("tgm2p-trainer: listening on " .. uri)
		else        emu.print_verbose("tgm2p-trainer: could not open " .. uri .. " (running inert)") end
	end

	local function rearm_socket()
		have_client = false
		rx_buffer = ""
		pcall(function() socket:close() end)
		socket = emu.file("", 7)
		open_socket()
		emu.print_verbose("tgm2p-trainer: re-armed listener (client disconnected)")
	end

	local function raw_write(str)
		if not socket_ok then return 0 end
		local ok, n = pcall(function() return socket:write(str) end)
		if not ok then return 0 end
		return n or 0
	end

	local function send(obj)
		raw_write(json.stringify(obj) .. "\n")
	end

	local function send_error(id, key, msg) send({ t = "error", id = id, key = key, msg = msg }) end

	local overrides = {}  -- key: { value, saved }
	local display_player = 0

	local function clear_one(key)
		local ov = overrides[key]
		if not ov then return end
		if classify(key) == "celldim" and space then
			local c = MAP.celldim[key]
			if c.doubles_live_byte then pcall(set_live_byte, c.doubles_live_byte, false) end
			for p = 0, (MAP.meta.players and MAP.meta.players.count or 1) - 1 do
				pcall(celldim_apply, c, false, p)
				if c.native_flag_addr then
					pcall(function()
						local a = player_addr(tonumber(c.native_flag_addr), p)
						space:write_u32(a, read_raw(a, 4) & ~tonumber(c.native_flag_bit or "0x200000") & 0xffffffff)
					end)
				end
			end
			overrides[key] = nil
			return
		end
		
		if classify(key) == "table" then
			local t = MAP.tables[key]
			if t.always then
				ov.value = -1
				return
			end
			overrides[key] = nil
			return
		end
		if classify(key) == "das" then
			ov.value = -1
			return
		end
		if classify(key) == "address" then
			pcall(apply_also_or, MAP.addresses[key], ov.players, false)
		end
		if is_sticky(key) and ov.saved and space then
			for p, val in pairs(ov.saved) do pcall(write_named, key, val, p) end
		end
		overrides[key] = nil
	end

	-- ---- host-input hotkeys ------------------------------------------
	-- MAME abstracts host keys across OSes, so we poll them here every frame
	-- instead of installing an OS-specific global keyboard hook. The GUI sends
	-- bindings (set_hotkeys); we report press / tap / hold edges back over the
	-- socket and the GUI runs the bound action. Fires only while MAME holds
	-- input focus, which is exactly when a practice hotkey is wanted.
	local input_mgr
	local mod_codes               -- name -> { code, ... } (resolved lazily)
	local hotkeys = {}            -- list of active entries
	local pending_hotkeys         -- bindings received before input was ready

	local MOD_TOKENS = {
		ctrl  = { "KEYCODE_LCONTROL", "KEYCODE_RCONTROL" },
		shift = { "KEYCODE_LSHIFT",   "KEYCODE_RSHIFT"   },
		alt   = { "KEYCODE_LALT",     "KEYCODE_RALT"     },
		win   = { "KEYCODE_LWIN",     "KEYCODE_RWIN"     },
	}

	local function input_ready()
		if input_mgr then return true end
		local ok, mgr = pcall(function() return manager.machine.input end)
		if not ok or not mgr then return false end
		input_mgr = mgr
		mod_codes = {}
		for name, toks in pairs(MOD_TOKENS) do
			local codes = {}
			for _, tk in ipairs(toks) do
				local cok, c = pcall(function() return input_mgr:code_from_token(tk) end)
				if cok and c then codes[#codes + 1] = c end
			end
			mod_codes[name] = codes
		end
		return true
	end

	local function mods_down(mods)
		if not mods or #mods == 0 then return true end
		for _, name in ipairs(mods) do
			local codes = mod_codes[name]
			local any = false
			if codes then
				for _, c in ipairs(codes) do
					if input_mgr:code_pressed(c) then any = true; break end
				end
			end
			if not any then return false end
		end
		return true
	end

	local function set_hotkeys(list)
		hotkeys = {}
		if not input_ready() then
			pending_hotkeys = list   -- rebuild once a machine (and input) exists
			return
		end
		pending_hotkeys = nil
		local tps = emu.osd_ticks_per_second()
		for _, b in ipairs(list or {}) do
			local ok, code = pcall(function() return input_mgr:code_from_token(b.token or "") end)
			if ok and code then
				local ms = tonumber(b.hold_ms) or 400
				hotkeys[#hotkeys + 1] = {
					action = b.action, code = code, mods = b.mods,
					kind = b.kind or "press",
					hold_ticks = math.floor(ms / 1000 * tps),
					down = false, down_tick = 0, hold_fired = false,
				}
			end
		end
	end

	local function poll_hotkeys()
		if pending_hotkeys and input_ready() then set_hotkeys(pending_hotkeys) end
		if #hotkeys == 0 or not input_ready() then return end
		local now = emu.osd_ticks()
		for _, e in ipairs(hotkeys) do
			local active = input_mgr:code_pressed(e.code) and mods_down(e.mods)
			if active and not e.down then
				e.down, e.down_tick, e.hold_fired = true, now, false
				if e.kind == "press" then
					send({ t = "hotkey", action = e.action, event = "press" })
				end
			elseif active and e.down then
				if e.kind == "taphold" and not e.hold_fired
						and (now - e.down_tick) >= e.hold_ticks then
					e.hold_fired = true
					send({ t = "hotkey", action = e.action, event = "hold" })
				end
			elseif (not active) and e.down then
				e.down = false
				if e.kind == "taphold" and not e.hold_fired then
					send({ t = "hotkey", action = e.action, event = "tap" })
				end
			end
		end
	end

	local function handle(msg)
		local t = msg.t
		if t == "hello" then
			send({ t = "hello", version = exports.version,
			       rom = emu.romname(), addr_version = (MAP.meta and MAP.meta.version) or 0 })
		elseif t == "ping" then
			send({ t = "ack", id = msg.id })
		elseif t == "set_override" then
			local ok, err = validate_override(msg.key, msg.value)
			if not ok then send_error(msg.id, msg.key, err); return end

			local k = classify(msg.key)
			if k == "celldim" and msg.value == 0 then
				clear_one(msg.key)
				send({ t = "ack", id = msg.id, key = msg.key })
				return
			end
			local ov = overrides[msg.key] or {}
			ov.value = msg.value

			local newp = msg.players or ov.players or { 0 }
			if k == "table" or k == "das" or k == "celldim" then newp = { 0 } end
			if k == "address" and is_sticky(msg.key) and space then
				ov.saved = (type(ov.saved) == "table") and ov.saved or {}
				local want = {}
				for _, p in ipairs(newp) do want[p] = true end
				for p, val in pairs(ov.saved) do
					if not want[p] then pcall(write_named, msg.key, val, p); ov.saved[p] = nil end
				end
				for _, p in ipairs(newp) do
					if ov.saved[p] == nil then
						local rok, val = pcall(read_named, msg.key, p)
						if rok then ov.saved[p] = val end
					end
				end
			elseif k == "table" and is_sticky(msg.key) and ov.saved == nil and space then
				local saved = {}
				for _, p in ipairs(MAP.tables[msg.key].pointers) do
					saved[#saved + 1] = space:read_u32(tonumber(p))
				end
				ov.saved = saved
			end
			ov.players = newp
			overrides[msg.key] = ov
			send({ t = "ack", id = msg.id, key = msg.key })
		elseif t == "clear_override" then
			clear_one(msg.key)
			send({ t = "ack", id = msg.id, key = msg.key })
		elseif t == "clear_all" then
			for key in pairs(overrides) do clear_one(key) end
			send({ t = "ack", id = msg.id })
		elseif t == "set_players" then
			display_player = (msg.players and msg.players[1]) or 0
			send({ t = "ack", id = msg.id })
		elseif t == "read" then
			if not space then send_error(msg.id, msg.key, "machine not running"); return end
			local ok, val = pcall(read_named, msg.key)
			if ok then send({ t = "read_result", id = msg.id, key = msg.key, value = val })
			else send_error(msg.id, msg.key, tostring(val)) end
		elseif t == "write" then
			if not space then send_error(msg.id, msg.key, "machine not running"); return end
			local ok, err = pcall(function ()
				for _, p in ipairs(msg.players or { 0 }) do write_named(msg.key, msg.value, p) end
			end)
			if ok then send({ t = "ack", id = msg.id, key = msg.key })
			else send_error(msg.id, msg.key, tostring(err)) end
		elseif t == "peek" then
			if not space then send_error(msg.id, nil, "machine not running"); return end
			local a, size = tonumber(msg.addr), msg.size or 1
			if not a then send_error(msg.id, nil, "bad addr"); return end
			local ok, val = pcall(function()
				if size == 1 then return space:read_u8(a)
				elseif size == 2 then return space:read_u16(a)
				else return space:read_u32(a) end
			end)
			if ok then send({ t = "peek_result", id = msg.id, addr = msg.addr, size = size, value = val })
			else send_error(msg.id, nil, tostring(val)) end
		elseif t == "poke" then
			if not space then send_error(msg.id, nil, "machine not running"); return end
			local a, size, v = tonumber(msg.addr), msg.size or 1, msg.value or 0
			if not a then send_error(msg.id, nil, "bad addr"); return end
			local ok, err = pcall(function()
				if size == 1 then space:write_u8(a, v & 0xff)
				elseif size == 2 then space:write_u16(a, v & 0xffff)
				else space:write_u32(a, v & 0xffffffff) end
			end)
			if ok then send({ t = "ack", id = msg.id })
			else send_error(msg.id, nil, tostring(err)) end
		elseif t == "dump" then
			if not space then send_error(msg.id, nil, "machine not running"); return end
			local a, len = tonumber(msg.addr), math.min(msg.len or 64, 4096)
			if not a then send_error(msg.id, nil, "bad addr"); return end
			local ok, hex = pcall(function()
				local parts = {}
				for i = 0, len - 1 do parts[i + 1] = string.format("%02x", space:read_u8(a + i)) end
				return table.concat(parts)
			end)
			if ok then send({ t = "dump_result", id = msg.id, addr = msg.addr, len = len, hex = hex })
			else send_error(msg.id, nil, tostring(hex)) end
		elseif t == "get_overrides" then
			local active = {}
			for key, ov in pairs(overrides) do active[key] = ov.value end
			send({ t = "overrides", id = msg.id, active = active })
		elseif t == "reload_config" then
			local ok, err = load_config()
			if ok then send({ t = "ack", id = msg.id })
			else send_error(msg.id, nil, err) end
		elseif t == "set_hotkeys" then
			set_hotkeys(msg.bindings)
			send({ t = "ack", id = msg.id })
		elseif t == "osd" then
			if type(msg.text) == "string" and msg.text ~= "" then
				pcall(function() manager.machine:popmessage(msg.text) end)
			end
		else
			send_error(msg.id, nil, "unknown command: " .. tostring(t))
		end
	end

	local function dispatch_line(line)
		local obj, _, err = json.parse(line)
		if not obj then send_error(nil, nil, "parse error: " .. tostring(err)); return end
		local ok, herr = pcall(handle, obj)
		if not ok then send_error(obj.id, obj.key, tostring(herr)) end
	end

	local function pump_socket()
		if not socket_ok then return end
		while true do
			local chunk = socket:read(4096) 
			if not chunk or #chunk == 0 then break end
			rx_buffer = rx_buffer .. chunk
			have_client = true
		end
		while true do
			local nl = rx_buffer:find("\n", 1, true)
			if not nl then break end
			local line = rx_buffer:sub(1, nl - 1):gsub("\r$", "")
			rx_buffer = rx_buffer:sub(nl + 1)
			if #line > 0 then dispatch_line(line) end
		end
		if #rx_buffer > 65536 then rx_buffer = "" end
	end

	local frame_count = 0
	local last_state_str = ""
	local last_state_frame = 0

	local function maybe_emit_state()
		local fields = MAP.state_fields or {}
		local snap = { t = "state", player = display_player }
		for _, key in ipairs(fields) do
			local ok, val = pcall(read_named, key, display_player)
			if ok then snap[key] = val end
		end
		local s = json.stringify(snap)
		if s ~= last_state_str or (frame_count - last_state_frame) >= 30 then
			last_state_str = s
			last_state_frame = frame_count
			send(snap)
		end
	end

	local function maybe_emit_heartbeat()
		if (frame_count % 30) == 0 then
			local payload = json.stringify({ t = "heartbeat", frame = frame_count, running = (space ~= nil) }) .. "\n"
			local n = raw_write(payload)
			if have_client and n < #payload then rearm_socket() end
		end
	end

	local reset_subscription = emu.add_machine_reset_notifier(function ()
		acquire_cpu()
		rx_buffer = ""
		table_filled = {}
	end)

	local stop_subscription = emu.add_machine_stop_notifier(function ()
		cpu = nil
		space = nil
	end)

	local frame_subscription = emu.add_machine_frame_notifier(function ()
		frame_count = frame_count + 1
		if not space then acquire_cpu() end
		pump_socket()
		pcall(poll_hotkeys)   -- host-input hotkeys; independent of game RAM
		if space then
			for key, t in pairs(MAP.tables) do
				if t.always and overrides[key] == nil then overrides[key] = { value = -1 } end
			end
			for key, d in pairs(MAP.dasfx) do
				if d.always and overrides[key] == nil then overrides[key] = { value = -1 } end
			end
			for _, cp in pairs(MAP.codepatches) do
				if cp.always then pcall(apply_codepatch, cp) end
			end
			for key, ov in pairs(overrides) do
				local ok, err = pcall(apply_override, key, ov.value, ov.players)
				if not ok then emu.print_verbose("tgm2p-trainer: apply '" .. key .. "' failed: " .. tostring(err)) end
			end
			maybe_emit_state()
		end
		maybe_emit_heartbeat()
	end)

	tgmtrainer._subs = { reset_subscription, stop_subscription, frame_subscription }

	load_config()
	open_socket()
end

return exports
