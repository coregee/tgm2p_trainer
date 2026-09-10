local Input={}
function Input.new(send)
 local api={}
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

	function api.set(list)
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

	function api.poll()
		if pending_hotkeys and input_ready() then api.set(pending_hotkeys) end
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

 return api
end
return Input
