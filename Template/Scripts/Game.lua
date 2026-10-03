-- The game. Startup.lua puts this script on the game's first node: Create runs once, Tick every frame.
Game = {}

function Game:Create()
    -- the whole screen: stretched to its parent, no margins (a canvas with no parent: the screen)
    self:SetAnchorMode(AnchorMode.FullStretch)
    self:SetMargins(0.0, 0.0, 0.0, 0.0)
    self.presses = 0
    self.text = self:CreateChild("Text")
    self.text:SetAnchorMode(AnchorMode.FullStretch)
    self.text:SetMargins(0.0, 0.0, 0.0, 0.0)
    self.text:SetHorizontalJustification(Justification.Center)
    self.text:SetVerticalJustification(Justification.Center)
    self.text:SetTextSize(36.0)
    self:Show()
end

function Game:Tick(deltaTime)
    if (Input.IsGamepadPressed(Gamepad.A)) then
        self.presses = self.presses + 1
        self:Show()
    end
end

function Game:Show()
    self.text:SetText(string.format("Hello, GameCube!\nPress A  (%d)", self.presses))
end
