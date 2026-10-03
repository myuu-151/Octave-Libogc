Log.Debug("Running EngineStartup.lua")

-- What the memory card screen shows beside a game's saves: the project's Scripts/SaveInfo.lua, if it has one
--   SaveInfo = { title = "...", description = "...", icon = "<hex>", banner = "<hex>" }
-- (the formats are System.SetSaveInfo's; DolphinWorks makes and edits the file). Handed to the engine here, so
-- a game needs no code for it; a game that sets its own later (System.SetSaveInfo) has the last word.
if (System.SetSaveInfo ~= nil) then
    Script.Require("SaveInfo")
    if (SaveInfo ~= nil and SaveInfo.icon ~= nil) then
        local ok, err = pcall(System.SetSaveInfo, SaveInfo.title or "", SaveInfo.description or "", SaveInfo.icon, SaveInfo.banner)
        if (not ok) then
            Log.Error("SaveInfo.lua: " .. tostring(err))
        end
    end
end
