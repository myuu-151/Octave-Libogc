-- Runs once when the game starts, before its first frame. A game made in code starts here, with no
-- scene: this makes the game's first node, a canvas the size of the screen, and puts Game.lua on it.
local game = Engine.GetWorld():SpawnNode("Canvas")
game:SetName("Game")
game:SetScriptFile("Game.lua")
